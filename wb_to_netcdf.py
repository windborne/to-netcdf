import os
import time
import datetime
import numpy as np
import jwt
import requests
import argparse
import xarray as xr
import pandas as pd

"""
In this section, we define the helper functions to access the WindBorne API
This is described in https://windbornesystems.com/docs/api
"""


def wb_get_request(url):
    """
    Make a GET request to WindBorne, authorizing with WindBorne correctly
    """

    client_id = os.environ['WB_CLIENT_ID']  # Make sure to set this!
    api_key = os.environ['WB_API_KEY']  # Make sure to set this!

    # create a signed JSON Web Token for authentication
    # this token is safe to pass to other processes or servers if desired, as it does not expose the API key
    signed_token = jwt.encode({
        'client_id': client_id,
        'iat': int(time.time()),
    }, api_key, algorithm='HS256')

    # make the request, checking the status code to make sure it succeeded
    response = requests.get(url, auth=(client_id, signed_token))
    response.raise_for_status()

    # return the response body
    return response.json()

"""
In this section, we have the core functions to convert data to netcdf
"""
def convert_to_netcdf(data, mission_name, curtime, bucket_hours ):
    # This module outputs data in netcdf format for the WMO ISARRA program.  The output format is netcdf
    #   and the style (variable names, file names, etc.) are described here:
    #  https://github.com/synoptic/wmo-uasdc/tree/main/raw_uas_to_netCDF

    # Mapping of WindBorne names to ISARRA names
    rename_dict = {
        'latitude' : 'lat',
        'longitude' : 'lon',
        'altitude' : 'altitude',
        'temperature' : 'air_temperature',
        'wind_direction' : 'wind_direction',
        'wind_speed' : 'wind_speed',
        'pressure' : 'air_pressure',
        'humidity_mixing_ratio' : 'humidity_mixing_ratio',
        'index' : 'obs',
    }

    # Put the data in a panda datafram in order to easily push to xarray then netcdf output
    df = pd.DataFrame(data)
    ds = xr.Dataset.from_dataframe(df)

    # Build the filename and save some variables for use later
    mt = datetime.datetime.fromtimestamp(curtime, tz=datetime.timezone.utc)
    outdatestring = mt.strftime('%Y%m%d%H%M%S')
    mission_name = ds['mission_name'].data[0]
    output_file = 'WindBorne_W-{}_{}Z.nc'.format(mission_name[2:6],outdatestring)

    # Derived quantities calculated here:

    # convert from specific humidity to humidity_mixing_ratio
    mg_to_kg = 1000000.
    if not all(x is None for x in ds['specific_humidity'].data):
        ds['humidity_mixing_ratio'] = (ds['specific_humidity'] / mg_to_kg) / (1 - (ds['specific_humidity'] / mg_to_kg))
    else:
        ds['humidity_mixing_ratio'] = ds['specific_humidity']

    # Wind speed and direction from components
    ds['wind_speed'] = np.sqrt(ds['speed_u']*ds['speed_u'] + ds['speed_v']*ds['speed_v'])
    ds['wind_direction'] = np.mod(180 + (180 / np.pi) * np.arctan2(ds['speed_u'], ds['speed_v']), 360)

    ds['time'] = ds['timestamp'].astype(float)
    ds = ds.assign_coords(time=("time", ds['time'].data))

    # Now that calculations are done, remove variables not needed in the netcdf output
    ds = ds.drop_vars(['humidity', 'speed_u', 'speed_v', 'specific_humidity',
                       'timestamp', 'mission_name'])

    # Rename the variables
    ds = ds.rename(rename_dict)

    # Adding attributes to variables in the xarray dataset
    ds['time'].attrs = {'units': 'seconds since 1970-01-01T00:00:00', 'long_name': 'Time', '_FillValue': float('nan'),
                        'processing_level': ''}
    ds['lat'].attrs = {'units': 'degrees_north', 'long_name': 'Latitude', '_FillValue': float('nan'),
                       'processing_level': ''}
    ds['lon'].attrs = {'units': 'degrees_east', 'long_name': 'Longitude', '_FillValue': float('nan'),
                       'processing_level': ''}
    ds['altitude'].attrs = {'units': 'meters_above_sea_level', 'long_name': 'Altitude', '_FillValue': float('nan'),
                            'processing_level': ''}
    ds['air_temperature'].attrs = {'units': 'Kelvin', 'long_name': 'Air Temperature', '_FillValue': float('nan'),
                                   'processing_level': ''}
    ds['wind_speed'].attrs = {'units': 'm/s', 'long_name': 'Wind Speed', '_FillValue': float('nan'),
                              'processing_level': ''}
    ds['wind_direction'].attrs = {'units': 'degrees', 'long_name': 'Wind Direction', '_FillValue': float('nan'),
                                  'processing_level': ''}
    ds['humidity_mixing_ratio'].attrs = {'units': 'kg/kg', 'long_name': 'Humidity Mixing Ratio',
                                         '_FillValue': float('nan'), 'processing_level': ''}
    ds['air_pressure'].attrs = {'units': 'Pa', 'long_name': 'Atmospheric Pressure', '_FillValue': float('nan'),
                                'processing_level': ''}

    # Add Global Attributes synonymous across all UASDC providers
    ds.attrs['Conventions'] = "CF-1.8, WMO-CF-1.0"
    ds.attrs['wmo__cf_profile'] = "FM 303-2024"
    ds.attrs['featureType'] = "trajectory"

    # Add Global Attributes unique to Provider
    ds.attrs['platform_name'] = "WindBorne Global Sounding Balloon"
    ds.attrs['flight_id'] = mission_name
    ds.attrs['site_terrain_elevation_height'] = 'not applicable'
    ds.attrs['processing_level'] = "b1"
    ds.to_netcdf(output_file)

def output_data(accumulated_observations, mission_name, starttime, bucket_hours):
    accumulated_observations.sort(key=lambda x: x['timestamp'])

    # Here, set the earliest time of data to be the first observation time, then set it to the most recent
    #    start of a bucket increment.
    # The reason to do this rather than using the input starttime, is because sometimes the data
    #    doesn't start at the start time, and the underlying output would try to output data that doesn't exist
    #
    accumulated_observations.sort(key=lambda x: x['timestamp'])
    earliest_time = accumulated_observations[0]['timestamp']
    if (earliest_time < starttime):
        print("Something is wrong: how can we have gotten data from before the starttime?")
    curtime = earliest_time - earliest_time % (bucket_hours * 60 * 60)

    start_index = 0
    for i in range(len(accumulated_observations)):
        if accumulated_observations[i]['timestamp'] - curtime > bucket_hours * 60 * 60:
            segment = accumulated_observations[start_index:i]
            print(f"Converting {len(segment)} observation(s) and saving as netcdf")
            convert_to_netcdf(segment, mission_name, curtime, bucket_hours)

            start_index = i
            curtime += datetime.timedelta(hours=bucket_hours).seconds

    # Cover any extra data within the latest partial bucket
    segment = accumulated_observations[start_index:]
    print(f"Converting {len(segment)} observation(s) and saving as netcdf")
    convert_to_netcdf(segment, mission_name, curtime, bucket_hours)

def main():
    """
    Queries WindBorne API for data from the input time range and converts it to prepbufr
    :return:
    """

    parser = argparse.ArgumentParser(description="""
    Retrieves WindBorne data and output to netcdf format.
    
    Files will be broken up into time buckets as specified by the --bucket_hours option, 
    and the output file names will contain the time at the mid-point of the bucket. For 
    example, if you are looking to have files centered on say, 00 UTC 29 April, the start time
    should be 3 hours prior to 00 UTC, 21 UTC 28 April.
    """, formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument("times", nargs='+',
                        help='Starting and ending times to retrieve obs.  Format: YYYY-mm-dd_HH:MM '
                             'Ending time is optional, with current time used as default')
    parser.add_argument('-b', '--bucket_hours', type=float, default=6.0,
                        help='Number of hours of observations to accumulate into a file before opening the next file')
    args = parser.parse_args()

    if (len(args.times) == 1):
        starttime=int(datetime.datetime.strptime(args.times[0], '%Y-%m-%d_%H:%M').
                   replace(tzinfo=datetime.timezone.utc).timestamp())
        endtime=int(datetime.datetime.now().timestamp())
    elif (len(args.times) == 2):
        starttime=int(datetime.datetime.strptime(args.times[0], '%Y-%m-%d_%H:%M').
                   replace(tzinfo=datetime.timezone.utc).timestamp())
        endtime=int(datetime.datetime.strptime(args.times[1], '%Y-%m-%d_%H:%M').
                 replace(tzinfo=datetime.timezone.utc).timestamp())
    else:
        print("error processing input args, one or two arguments are needed")
        exit(1)

    if (not "WB_CLIENT_ID" in os.environ) or (not "WB_API_KEY" in os.environ) :
        print("  ERROR: You must set environment variables WB_CLIENT_ID and WB_API_KEY\n"
              "  If you don't have a client ID or API key, please contact WindBorne.")
        exit(1)

    args = parser.parse_args()
    bucket_hours = args.bucket_hours

    observations_by_mission = {}
    accumulated_observations = []
    has_next_page = True

    # This line here would just find W-1594, useful for testing/debugging
    #next_page = f"https://sensor-data.windbornesystems.com/api/v1/super_observations.json?mission_id=c8108dd5-bcf5-45ec-be80-a1da5e382e99&min_time={starttime}&max_time={endtime}&include_mission_name=true"

    next_page = f"https://sensor-data.windbornesystems.com/api/v1/super_observations.json?min_time={starttime}&max_time={endtime}&include_mission_name=true"

    while has_next_page:
        # Note that we query superobservations, which are described here:
        # https://windbornesystems.com/docs/api#super_observations
        # We find that for most NWP applications this leads to better performance than overwhelming with high-res data
        print(next_page)
        observations_page = wb_get_request(next_page)
        has_next_page = observations_page["has_next_page"]
        if (len(observations_page['observations']) == 0):
            print("Could not find any observations for the input date range!!!!")
        if has_next_page:
            next_page = observations_page["next_page"]+"&include_mission_name=true&min_time={}&max_time={}".format(starttime,endtime)
        print(f"Fetched page with {len(observations_page['observations'])} observation(s)")
        for observation in observations_page['observations']:
            if 'mission_name' not in observation:
                print("got an ob without a mission name???")
                continue
            elif observation['mission_name'] not in observations_by_mission:
                observations_by_mission[observation['mission_name']] = []

            observations_by_mission[observation['mission_name']].append(observation)
            accumulated_observations.append(observation)

            # alternatively, you could call `time.sleep(60)` and keep polling here for real-time data


    if len(observations_by_mission) == 0:
        print("No observations found")
        return

    for mission_name, accumulated_observations in observations_by_mission.items():
        output_data(accumulated_observations, mission_name, starttime, bucket_hours)

if __name__ == '__main__':
    main()
