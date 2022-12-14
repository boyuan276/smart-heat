import time, os, sys, pathlib
import pandas as pd
import dask.dataframe as dd
import numpy as np
sys.path.append(f'{pathlib.Path(os.path.abspath("")).parents[0]}')

# User Packages
try:
    import cop
except Exception as e:
    from . import cop

"""
Module used for processing raw, individual thermostat files into dataframes that are useful for aggregate analysis.
"""

def get_effective_runtime(df, season):

    """
    Converts multi-stage runtimes into single, effective runtime. We assume equal weighting for each stage's runtime
    (i.e., each stage adds the same amount of power), but this can be converted into a weighted average if the first
    stage adds more power than the second
    :param df:
    :return:
    """

    # Winter: calculate effective heating runtime
    # compHeat1,2,3: Runtime (seconds) for heat-pumps used in heating
    # auxHeat1,2,3: Runtime (seconds) for any heat source other than a heat pump
    if season == 'winter':
        # Determine if heat pump is used
        # Calculate effective running time of heat pumps: effectiveCompRun
        # with different heat pump stages
        if (df['compHeat2'] > 0).any():
            # Two stage heat pump
            df['effectiveCompRun'] = df[['compHeat1', 'compHeat2']].mean(axis=1)
            df['countCompRun'] = df['compHeat1'].notna() & df['compHeat2'].notna()
            has_hp=True
        elif (df['compHeat1'] > 0).any():
            # One stage heat pump
            df['effectiveCompRun'] = df['compHeat1']
            df['countCompRun'] = df['compHeat1'].notna()
            has_hp=True
        else:
            has_hp=False

        if has_hp:
            # Get Auxillary Gas Heat Runtime
            # With heat pump, calculate average aux heat runtime: effectiveAuxRun
            # with different number of aux heat sources
            if (df['auxHeat2'] > 0).any() and (df['auxHeat3'] > 0).any():
                # Three aux heat sources
                df['effectiveAuxRun'] = df[['auxHeat1', 'auxHeat2', 'auxHeat3']].mean(axis=1)
                df['countAuxRun'] = df['auxHeat1'].notna() & df['auxHeat2'].notna() & df['auxHeat3'].notna()

            elif (df['auxHeat2'] > 0).any():
                # Two aux heat sources
                df['effectiveAuxRun'] = df[['auxHeat1', 'auxHeat2']].mean(axis=1)
                df['countAuxRun'] = df['auxHeat1'].notna() & df['auxHeat2'].notna()

            else:
                # Only one aux heat source
                df['effectiveAuxRun'] = df['auxHeat1']
        else:
            # Get Regular Aux Heat Runtime: effectiveGasRun
            # Without heat pump, aux heat (gas) is main source of heat
            if (df['auxHeat2'] > 0).any():
                # Two or three aux heat sources
                df['effectiveGasRun'] = df[['auxHeat1', 'auxHeat2']].mean(axis=1)
                df['countGasRun'] = df['auxHeat1'].notna() & df['auxHeat2'].notna()

            elif (df['auxHeat2'] > 0).any() and (df['auxHeat3'] > 0).any():
                # Three aux heat sources
                df['effectiveGasRun'] = df[['auxHeat1', 'auxHeat2', 'auxHeat3']].mean(axis=1)
                df['countGasRun'] = df['auxHeat1'].notna() & df['auxHeat2'].notna() & df['auxHeat3'].notna()

            else:
                # Only one aux heat source
                df['effectiveGasRun'] = df['auxHeat1']
                df['countGasRun'] = df['auxHeat1'].notna()
    
    # Summer: calculate effective cooling runtime
    elif season == 'Summer':
        if (df['compCool2'] > 0).any():
            df['effectiveCompRun'] = df[['compCool1', 'compCool2']].mean(axis=1)
            df['countCompRun'] = df['compCool1'].notna() & df['compCool2'].notna()
            has_hp=True
        elif (df['compCool1'] > 0).any():
            df['effectiveCompRun'] = df['compHeat1']
            df['countCompRun'] = df['compCool1'].notna()
            has_hp=True
        else:
            has_hp=False

    else:
        raise ValueError(f'Wrong season: {season}!')

    return df

def get_effective_power(df, season):
    """
    Converts runtime into power consumption. Contains support for testing scaling factors for converting between systems.
    For example, if auxiliary heat were converted into a heat pump the power consumption could be reduced by some factor
    in order to provide the same amount of heat. We term this factor "eta", but it is very difficult in practice to
    approximate this scaling. Thus, this function currently has no affect on presented results.
    :param df:
    :return:
    """

    if season == 'winter':
        # Get Estimated COP at each time step
        HSPF = 10
        df['cop'] = cop.calc_cop_v(df['T_ctrl_C'], df['T_out_C'], HSPF, season)

        if 'effectiveGasRun' in df.columns:
            # Non-heat pump heating
            # Convert gas runtime to electric runtime using heat pump's COP
            df['gasElectricalDemandASHP'] = df['effectiveGasRun'] / df['cop']
            df['effectiveElectricPower'] = np.nan
            df['effectiveElectricPower_w/out_aux'] = np.nan
            df['effectiveHeat'] = df['effectiveGasRun']

        elif 'effectiveCompRun' in df.columns:
            # Heat pump heating
            # Electric power = heat pump + aux heat

            # Coef. for converting aux heat runtime to heat pump runtime # FIXME
            # df['eta'] = cop.calc_cop(21.11, df['Design_Temp_C'][0]) * cop.calc_power(df['Design_Temp_C'][0], HSPF) # Eta calculated based on design temps
            df['eta'] = 1 # constant eta for testing

            df['effectiveCompPower'] = cop.calc_power_v(df['T_out_C'], HSPF) * df['effectiveCompRun']
            df['effectiveAuxPower'] = df['eta'] * df['effectiveAuxRun']
            df['effectiveCompHeat'] = df['effectiveCompPower'] * df['cop']
            df['effectiveAuxHeat'] = df['effectiveAuxPower']
            df['effectiveHeat'] = df['effectiveCompRun'] + df['effectiveAuxRun'] # FIXME Not right but for testing
            df['effectiveElectricPower'] = df['effectiveCompPower'] + df['effectiveAuxPower']
            df['effectiveElectricPowerNoAux'] = df['effectiveCompPower'] + df['effectiveAuxPower'] / df['cop']
            df['effectiveCool'] = 0 # Place holder for formatting

    elif season == 'summer':
        # Get Estimated COP at each time step
        HSPF = 10 # FIXME: COP curve for cooling
        df['cop'] = cop.calc_cop_v(df['T_ctrl_C'], df['T_out_C'], HSPF, season)

        df['effectiveCompPower'] = cop.calc_power_v(df['T_out_C'], HSPF) * df['effectiveCompRun']
        df['effectiveCompCool'] = df['effectiveCompPower'] * df['cop']
        df['effectiveCool'] = df['effectiveCompRun']
        df['effectiveElectricPower'] = df['effectiveCompPower']
        df['effectiveHeat'] = 0 # Place holder for formatting

    else:
        raise ValueError(f'Wrong season: {season}!')

    return df


def group_dfs(df_list, size='small'):
    """
    Aggregates a list of dfs into a single, timeseries dataframe. 
    Normalizes the effectiveHeat or effectiveCool by the average to get
    normalized heating demand.
    :param df_list:
    :param size:
    :return:
    """
    df_list = [x for x in df_list if x is not None]

    if size == 'small':
        dtype_dict = {'T_ctrl_C': np.float16, 'T_out_C': np.float16,
                      # 'GHI_(kW/m2)': np.float32, 'Wind Speed': np.float32,
                      'effectiveHeat': np.float32, 'effectiveCool': np.float32,
                      'effectiveElectricPower': np.float32, 'fan': np.float32,
                      # 'Nearest_Lat': np.float32, '100m_Wind_Speed_(m/s)': np.float32
                      }
    else:
        dtype_dict = {'T_stp_cool': np.float32, 'T_stp_heat': np.float32, 'Humidity': np.float32,
                      'auxHeat1': np.float32, 'auxHeat2': np.float32, 'auxHeat3': np.float32,
                      'compCool1': np.float31, 'compCool2': np.float32,
                      'compHeat1': np.float32, 'compHeat2': np.float32, 'fan': np.float32,
                      'Thermostat_Temperature': np.float32, 'T_out': np.float32, 'RH_out': np.float32,
                      'T_ctrl': np.float32, 'T_ctrl_C': np.float32, 'T_out_C': np.float32,
                      # 'effectiveGasHeat': np.float32, 'effectiveGasPower': np.float32
                      }

    grouped_df = dd.concat(df_list).astype(dtype_dict)

    grouped_df = grouped_df.groupby('DateTime').mean().compute()

    # Normalize by average.
    grouped_df['effectiveElectricPowerNorm'] = grouped_df['effectiveElectricPower'] / np.mean(
        grouped_df['effectiveElectricPower'])
    grouped_df['effectiveHeatNorm'] = grouped_df['effectiveHeat']/np.mean(grouped_df['effectiveHeat'])
    grouped_df['effectiveCoolNorm'] = grouped_df['effectiveCool']/np.mean(grouped_df['effectiveCool'])

    return grouped_df

def group_dfs_by_location(df_list, size='small'):
    """
    Groups the dfs based on their nearest central location. Used to cluster individual thermostats into regions so that
    they can be compared to local weather conditions for renewable energy availability analysis.
    :param df_list:
    :param size:
    :return:
    """

    for df in df_list:
        df.index.rename('DateTime', inplace=True)

    if size == 'small':
        dtype_dict = {'T_ctrl_C': np.float16, 'T_out_C': np.float16,
                      # 'GHI_(kW/m2)': np.float16, 'Wind Speed': np.float16,
                      'effectiveHeat': np.float32, 'effectiveCool': np.float32,
                      'effectiveElectricPower': np.float16, 'fan': np.float16,
                      # '100m_Wind_Speed_(m/s)': np.float32,
                      # 'Nearest_Lat': np.float32
                      }
    else:
        dtype_dict = {'T_stp_cool': np.float16, 'T_stp_heat': np.float16, 'Humidity': np.float16,
                      'auxHeat1': np.float32, 'auxHeat2': np.float32, 'auxHeat3': np.float32,
                      'compCool1': np.float32, 'compCool2': np.float32,
                      'compHeat1': np.float32, 'compHeat2': np.float32, 'fan': np.float16,
                      'Thermostat_Temperature': np.float32, 'T_out': np.float32, 'RH_out': np.float16,
                      'T_ctrl': np.float32, 'T_ctrl_C': np.float32, 'T_out_C': np.float32,
                      'Nearest_Lat': np.float32, 'Nearest_Long': np.float32, 'Lat': np.float32, 'Long': np.float32
                      # 'effectiveGasHeat': np.float32, 'effectiveGasPower': np.float32
                      }

    grouped_df = dd.concat(df_list).astype(dtype_dict)
    grouped_df = grouped_df.groupby(['DateTime', 'Nearest_Lat']).mean().compute()

    # Get Normalized Heating
    grouped_df['effectiveHeatNorm'] = np.nan
    mean_per_lat = grouped_df.groupby(level=1).mean()
    for idx in mean_per_lat.index:
        grouped_df.loc[grouped_df.index.get_level_values(1) == idx, 'effectiveHeatNorm'] = \
            grouped_df.loc[grouped_df.index.get_level_values(1) == idx, 'effectiveHeat']/mean_per_lat.loc[idx, 'effectiveHeat']
    
    # Get Normalized Cooling
    grouped_df['effectiveCoolNorm'] = np.nan
    mean_per_lat = grouped_df.groupby(level=1).mean()
    for idx in mean_per_lat.index:
        grouped_df.loc[grouped_df.index.get_level_values(1) == idx, 'effectiveCoolNorm'] = \
            grouped_df.loc[grouped_df.index.get_level_values(1) == idx, 'effectiveCool']/mean_per_lat.loc[idx, 'effectiveCool']

    lats = []
    for df in df_list:
        lats.append(df['Nearest_Lat'].iloc[0])
    a, b = np.unique(lats, return_counts=True)
    lat_counts = dict(zip(a, b))

    include_lats = []
    for lat in lat_counts.keys():
        if lat_counts[lat] > 100:
            include_lats.append(lat)

    grouped_df = grouped_df.loc[pd.IndexSlice[:, include_lats], :]

    grouped_df['effectiveElectricPowerNorm'] = grouped_df['effectiveElectricPower'] / np.mean(
        grouped_df['effectiveElectricPower'])

    return grouped_df
