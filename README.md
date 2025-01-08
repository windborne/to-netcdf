# to-netcdf

This utility queries the [WindBorne API](https://windbornesystems.com/docs/api) and converts the files to prepbufr.
While it works out of the box, we encourage you to adapt it to your needs.

You will need to set the environment variables `WB_CLIENT_ID` and `WB_API_KEY`.
If you do not have these, you may request them by emailing data@windbornesystems.com.

## Installing dependencies & running

You will need the following other dependencies (which may well exist on your system):
1. numpy (`pip3 install numpy`)
2. pandas (`pip3 install pandas`)
3. xarray (`pip3 install xarray`)

From here, you should be able to go back to wherever this repository lives and run:
```bash
python3 wb_to_netcdf.py --help
```

## Assumptions
This utility is designed to be adapted to specific applications.
In the course of building it, we made several assumptions which may not be suited for your particular application, including:
- The formula for converting relative humidity to specific humidity. It uses formulas from GFS, which differ from formulas you may see elsewhere (eg metpy).
- How it divides up data to put in different files. It splits by balloon and by time period, such that a single file won't have more than three hours of data nor data from different balloon flights. It may make sense in some cases to reduce this time period.
- How much data it fetches from the WindBorne API. It is currently set to process only the last three hours of data and not to continue polling for more.
