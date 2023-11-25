import argparse
import logging
import os
import re
from pathlib import Path
import random
import sys
import tempfile
import zipfile
# Imports above are standard Python
# Imports below are 3rd-party
from lib.base import C, Database, Logger
from argparse_range import range_action
import pandas as pd
from dateutil.parser import parse
import numpy as np
import openpyxl
from openpyxl.styles import Border, Side, Alignment, Font, borders
import seaborn as sns

MAX_SHEET_NAME_LENGTH = 31  # Excel limitation
ROUNDING = 1  # 5.4% for example
OBJECT = "object"
VALUE, COUNT = "Value", "Count"

# When producing a list of detail values and their frequency of occurrence
DEFAULT_MAX_DETAIL_VALUES = 35
# When analyzing the patterns of a string column
DEFAULT_MAX_PATTERN_LENGTH = 50
# Don't plot distributions if there are fewer than this number of distinct values
DISTRIBUTION_PLOT_MIN_VALUES = 6
# Categorical plots should have no more than this number of distinct values
# Groups the rest in "Other"
CATEGORICAL_PLOT_MAX_VALUES = 5
OTHER = "Other"

# Plotting visual effects
PLOT_SIZE_X, PLOT_SIZE_Y = 11, 8.5
PLOT_FONT_SCALE = 0.75

ROW_COUNT = "count"
NULL_COUNT = "null"
NULL_PERCENT = "%null"
UNIQUE_COUNT = "unique"
UNIQUE_PERCENT = "%unique"
MOST_COMMON = "most_common"
MOST_COMMON_PERCENT = "%most_common"
LARGEST = "largest"
SMALLEST = "smallest"
LONGEST = "longest"
SHORTEST = "shortest"
MEAN = "mean"
PERCENTILE_25TH = "percentile_25th"
MEDIAN = "median"
PERCENTILE_75TH = "percentile_75th"
STDDEV = "stddev"

ANALYSIS_LIST = (
    ROW_COUNT,
    NULL_COUNT,
    NULL_PERCENT,
    UNIQUE_COUNT,
    UNIQUE_PERCENT,
    MOST_COMMON,
    MOST_COMMON_PERCENT,
    LARGEST,
    SMALLEST,
    LONGEST,
    SHORTEST,
    MEAN,
    PERCENTILE_25TH,
    MEDIAN,
    PERCENTILE_75TH,
    STDDEV,
)

parser = argparse.ArgumentParser(
    description='Profile the data in a CSV file or database table/view. Supported databases are: mssql, postgresql.',
    epilog='Generates an analysis consisting of an Excel workbook and (optionally) one or more images.'
)
parser.add_argument('input',
                    metavar="/path/to/input_data_file.csv | query",
                    help="If a file no connection information required.")
parser.add_argument('--db-host-name',
                    metavar="HOST_NAME",
                    help="Overrides environment variables.")
parser.add_argument('--db-port-number',
                    metavar="PORT_NUMBER",
                    help="Overrides environment variables.")
parser.add_argument('--db-name',
                    metavar="DATABASE_NAME",
                    help="Overrides environment variables.")
parser.add_argument('--db-user-name',
                    metavar="USER_NAME",
                    help="Overrides environment variables.")
parser.add_argument('--db-password',
                    metavar="PASSWORD",
                    help="Overrides environment variables.")
parser.add_argument('--header-lines',
                    type=int,
                    metavar="NUM",
                    action=range_action(1, sys.maxsize),
                    default=0,
                    help="When reading from a file specifies the number of rows to skip for header information. Ignored when getting data from a database. Default is 0.")
parser.add_argument('--sample-size',
                    type=int,
                    metavar="NUM",
                    action=range_action(1, sys.maxsize),
                    help=f"Randomly choose this number of rows. If greater than or equal to the number of data rows will use all rows.")
parser.add_argument('--max-detail-values',
                    type=int,
                    metavar="NUM",
                    action=range_action(1, sys.maxsize),
                    default=DEFAULT_MAX_DETAIL_VALUES,
                    help=f"Produce this many of the top/bottom value occurrences, default is {DEFAULT_MAX_DETAIL_VALUES}.")
parser.add_argument('--max-pattern-length',
                    type=int,
                    metavar="NUM",
                    action=range_action(1, sys.maxsize),
                    default=DEFAULT_MAX_PATTERN_LENGTH,
                    help=f"When segregating strings into patterns leave untouched strings of length greater than this, default is {DEFAULT_MAX_PATTERN_LENGTH}.")
parser.add_argument('--output-dir',
                    metavar="/path/to/dir",
                    default=Path.cwd(),
                    help="Default is the current directory.")

logging_group = parser.add_mutually_exclusive_group()
logging_group.add_argument('-v', '--verbose', action='store_true')
logging_group.add_argument('-t', '--terse', action='store_true')

args = parser.parse_args()
input_path = Path(args.input)
host_name = args.db_host_name
port_number = args.db_port_number
database_name = args.db_name
user_name = args.db_user_name
password = args.db_password
header_lines = args.header_lines
sample_percent = args.sample_percent
max_detail_values = args.max_detail_values
max_pattern_length = args.max_pattern_length
output_dir = Path(args.output_dir)

if host_name and not (port_number and database_name and user_name and password):
    parser.error("Connecting to a database requires: --db-host-name, --db-port-number, --db-name, --db-user-name, --db-password")
if not output_dir.exists():
    parser.error("Directory '{output_dir}' does not exist.")
if input_path.endswith(".csv"):
    pass

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s | %(levelname)8s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S %Z')
handler.setFormatter(formatter)
logger.addHandler(handler)
if args.verbose:
    handler.setLevel(logging.DEBUG)
elif args.terse:
    handler.setLevel(logging.WARNING)
else:
    handler.setLevel(logging.INFO)

jdbc_jar_file = None

import random
import pandas as pd

def select_random_rows(input_file, output_file, n):
    """
    Selects random n rows from a CSV file and exports them to a new CSV file.

    Args:
        input_file (str): Path to the input CSV file.
        output_file (str): Path to the output CSV file.
        n (int): Number of random rows to select.

    Returns:
        None
    """
    # Read the input CSV file into a pandas DataFrame
    df = pd.read_csv(input_file)

    # Check if the number of rows in the DataFrame is less than n
    if len(df) < n:
        raise ValueError("The number of rows in the input file is less than n.")

    # Select random n rows from the DataFrame
    random_rows = df.sample(n)

    # Export the selected random rows to a new CSV file
    random_rows.to_csv(output_file, index=False)

# # Example usage
# input_file = "input.csv"
# output_file = "output.csv"
# select_random_rows(input_file, output_file, 10
# )

# Now, read the data
if host_name:
    # User wants to get the data from a database table or view
    import jaydebeapi as jdbc
    # Construct connect string based on database type
    jdbc_path = Path(jdbc_jar_file)
    if not jdbc_path.exists():
        logger.critical(f"Cannot find JDBC driver path '{jdbc_jar_file}'.")
        sys.exit(1)
    logger.info(f"Connecting to '{database_name}' ...")
    if "postgres" in jdbc_path.name:
        class_name = 'org.postgresql.Driver'
        url = f"jdbc:postgresql://{host_name}:{port_number}/{database_name}"
        with jdbc.connect(class_name, url, [user_name, password], jdbc_jar_file) as connection:
            logger.info(f"Connected.")
            query = f"select * from {input_path}"
            if sample_percent:
                query += f" TABLESAMPLE SYSTEM ({sample_percent})"
            logger.info(f'Executing "{query}" ...')
            input_df = pd.read_sql(query, connection)
    elif "ojdbc" in jdbc_path.name:
        class_name = 'oracle.jdbc.OracleDriver'
        url = f"jdbc:oracle:thin:@//{host_name}:{port_number}/{database_name}"
        with jdbc.connect(class_name, url, [user_name, password], jdbc_jar_file) as connection:
            logger.info(f"Connected.")
            query = f"select * from {input_path}"
            if sample_percent:
                query += f" sample({sample_percent})"
            logger.info(f'Executing "{query}" ...')
            input_df = pd.read_sql(query, connection)
    else:
        logger.critical(f"Only Postgresql and Oracle supported.")
        sys.exit(1)
else:
    # Input is coming from a file
    if not input_path.exists():
        logger.critical(f"No such file '{args.input}' and database connection arguments not provided.")
        sys.exit(1)
    logger.info(f"Reading from '{input_path}' ...")
    skip_list = list()
    # Support sampling
    if sample_percent:
        header_size = args.header or 1
        number_of_rows = sum(1 for line in open(input_path)) - header_size
        sample_size = int(sample_percent * number_of_rows / 100)
        skip_list = sorted(random.sample(range(header_size, number_of_rows + 1), number_of_rows - sample_size))
    if args.header:
        input_df = pd.read_csv(input_path, skiprows=skip_list, header=args.header)
    else:
        input_df = pd.read_csv(input_path, skiprows=skip_list)
        # Next line: it's useful for debugging to focus on a single column
        # input_df = pd.read_csv(input_path, skiprows=skip_list, usecols=['activity_date'])


def parse_date(date):
    if date is np.nan:
        return np.nan
    else:
        return parse(date)  # dateutil's parser


def truncate_string(s, max_length, filler="..."):
    """
    For example, truncate_string("Hello world!", 7) returns:
    "Hell..."
    """
    excess_count = len(s) - max_length
    if excess_count <= 0:
        return s
    else:
        return s[:max_length-len(filler)] + filler


def set_best_type(series):
    """
    Set the type so as to give the most interesting/useful analysis
    :param series: a Pandas/Numpy series
    :return: prefer in this order:
    * integer
    * float
    * date
    * string
    """
    try:
        series = series.astype('int')
    except Exception:
        logger.debug("Not an integer column.")
        try:
            series = series.astype('float')
        except Exception:
            logger.debug("Not a float column.")
            try:
                series = series.apply(parse).astype('datetime64[ns]')
                # series = pd.to_datetime(series, infer_datetime_format=True)
            except Exception:
                logger.debug("Not a datetime column.")
    return series


def get_pattern(s, max_length=max_pattern_length):
    """
    Examples:
    "hi joe." --> "CC_CCC."
    "hello4abigail" --> "C(5)9C(7)"
    :param s: string data
    :return: a pattern analysis, for example abc-123 becomes CCC-999
    """
    if not s or len(s) > max_length:
        return s
    s = re.sub("[a-zA-Z]", "C", s)  # Replace letters with 'C'
    s = re.sub(r"\d", "9", s)  # Replace numbers with '9'
    s = re.sub(r"\s+", "_", s)  # Replace whitespace with '_'
    # Group long sequences of letters or numbers
    # See https://stackoverflow.com/questions/76230795/replace-characters-with-a-count-of-characters
    # The number below (2) means sequences of 3 or more will be grouped
    s = re.sub(r'(.)\1{2,}', lambda m: f'{m.group(1)}({len(m.group())})', s)
    return s


# Data has been read into input_df, now process it
# To temporarily hold distribution plots
tempdir = tempfile.TemporaryDirectory()
tempdir_path = Path(tempdir.name)
# To keep track of which columns have distribution plots
distribution_plot_list = list()

summary_dict = dict()  # To be converted into the summary worksheet
detail_dict = dict()  # Each element to be converted into a detail worksheet
pattern_dict = dict()  # For each string column calculate the frequency of patterns
for label in input_df.columns:
    logger.info(f"Working on column '{label}' ...")
    input_df[label] = set_best_type(input_df[label])
    data = input_df[label]
    logger.debug(f"Treating this column as data type '{data.dtype}'.")
    row_dict = dict.fromkeys(ANALYSIS_LIST)
    # Row count
    row_count = data.size
    if not row_count:
        logger.warning("No data.")
        sys.exit()
    row_dict[ROW_COUNT] = row_count
    # Null
    null_count = row_count - data.count()
    row_dict[NULL_COUNT] = null_count
    # Null%
    row_dict[NULL_PERCENT] = round(100 * null_count / row_count, ROUNDING)
    # Unique
    unique_count = len(data.unique())
    row_dict[UNIQUE_COUNT] = unique_count
    # Unique%
    row_dict[UNIQUE_PERCENT] = round(100 * unique_count / row_count, ROUNDING)

    if null_count != row_count:
        # Most common (mode)
        row_dict[MOST_COMMON] = list(data.mode().values)[0]
        # Most common%
        row_dict[MOST_COMMON_PERCENT] = round(100 * list(data.value_counts())[0] / row_count, ROUNDING)

        if data.dtype == OBJECT:
            # Largest & smallest
            row_dict[LARGEST] = data.dropna().astype(pd.StringDtype()).max()
            row_dict[SMALLEST] = data.dropna().astype(pd.StringDtype()).min()
            # Longest & shortest
            row_dict[LONGEST] = max(data.dropna().astype(pd.StringDtype()).values, key=len)
            row_dict[SHORTEST] = min(data.dropna().astype(pd.StringDtype()).values, key=len)
            # No mean/quartiles/stddev statistics for strings
        else:  # numeric or datetime
            # Largest & smallest
            row_dict[LARGEST] = data.max()
            row_dict[SMALLEST] = data.min()
            # No longest/shortest for dates and numbers
            # Mean/quartiles/stddev statistics
            row_dict[MEAN] = data.mean()
            row_dict[PERCENTILE_25TH] = data.quantile(0.25)
            row_dict[MEDIAN] = data.quantile(0.5)
            row_dict[PERCENTILE_75TH] = data.quantile(0.75)
            row_dict[STDDEV] = data.std()

        # Value counts
        # Collect no more than number of values available or what was given on the command-line
        # whichever is less
        detail_df = pd.DataFrame()
        max_length = min(max_detail_values, len(data.value_counts(dropna=False)))
        # Create 3-column ascending visual
        detail_df["rank"] = list(range(1, max_length + 1))
        detail_df["value"] = list(data.value_counts(dropna=False).index)[:max_length]
        detail_df["count"] = list(data.value_counts(dropna=False))[:max_length]
        percent_total_list = list(data.value_counts(dropna=False, normalize=True))[:max_length]
        detail_df["%total"] = [round(x*100, ROUNDING) for x in percent_total_list]
    else:
        logger.info(f"Column is empty.")

    summary_dict[label] = row_dict
    detail_dict[label] = detail_df

    # For string columns produce a pattern analysis
    # For numeric and datetime columns produce a distribution plot
    if data.dtype == OBJECT:  # string data
        pattern_df = pd.DataFrame()
        pattern_data = data.apply(get_pattern)
        pattern_analysis = pattern_data.value_counts(normalize=True)
        max_length = min(max_detail_values, len(pattern_data.value_counts(dropna=False)))
        pattern_df["rank"] = list(range(1, max_length + 1))
        pattern_df["pattern"] = list(pattern_data.value_counts(dropna=False).index)[:max_length]
        pattern_df["count"] = list(pattern_data.value_counts(dropna=False))[:max_length]
        percent_total_list = list(pattern_data.value_counts(dropna=False, normalize=True))[:max_length]
        pattern_df["%total"] = [round(x*100, ROUNDING) for x in percent_total_list]
        pattern_dict[label] = pattern_df
    else:  # Numeric/datetime data
        sns.set_theme()
        sns.set(font_scale=PLOT_FONT_SCALE)
        plot_data = data.value_counts(normalize=True)
        if len(plot_data) >= DISTRIBUTION_PLOT_MIN_VALUES:
            logger.debug("Creating a distribution plot ...")
            g = sns.displot(data)
            plot_output_path = tempdir_path / f"{label}.distribution.png"
            g.set_axis_labels(VALUE, COUNT, labelpad=10)
            g.figure.set_size_inches(PLOT_SIZE_X, PLOT_SIZE_Y)
            g.ax.margins(.15)
            g.savefig(plot_output_path)
            logger.info(f"Wrote {os.stat(plot_output_path).st_size} bytes to '{plot_output_path}'.")
            distribution_plot_list.append(label)
        else:
            logger.debug("Not enough distinct values to create a distribution plot.")

# Convert the summary_dict dictionary of dictionaries to a DataFrame
result_df = pd.DataFrame.from_dict(summary_dict, orient='index')
# And write it to a worksheet
logger.info("Writing summary ...")
# Set target filename based on database v. file and whether we are sampling
if host_name and sample_percent:
    output_file = (output_dir / f"{input_path}.sample{sample_percent}pct{EXCEL_EXTENSION}")
elif host_name and not sample_percent:
    output_file = (output_dir / f"{input_path}{EXCEL_EXTENSION}")
elif not host_name and sample_percent:
    output_file = (output_dir / f"{input_path.stem}.sample{sample_percent}pct{EXCEL_EXTENSION}")
elif not host_name and not sample_percent:
    output_file = (output_dir / f"{input_path.stem}{EXCEL_EXTENSION}")
else:
    raise("Programming error.")
writer = pd.ExcelWriter(output_file, engine='xlsxwriter')
result_df.to_excel(writer, sheet_name="Summary")
# And generate a detail sheet, and optionally a pattern sheet, for each column
for label, detail_df in detail_dict.items():
    logger.info(f"Writing detail for column '{label}' ...")
    detail_df.to_excel(writer, index=False, sheet_name=truncate_string(label+" detail", MAX_SHEET_NAME_LENGTH))
    if label in pattern_dict:
        logger.info(f"Writing pattern detail for string column '{label}' ...")
        pattern_df = pattern_dict[label]
        pattern_df.to_excel(writer, index=False, sheet_name=truncate_string(label + " pattern", MAX_SHEET_NAME_LENGTH))
writer.close()

# Add the plots and size bars to the Excel file
workbook = openpyxl.load_workbook(output_file)

# Plots
# Look for sheet names corresponding to the plot filename
sheet_number = -1
for sheet_name in workbook.sheetnames:
    sheet_number += 1
    if sheet_number == 0:  # Skip summary sheet (first sheet, zero-based-index)
        continue
    column_name = sheet_name[:-7]  # remove " detail" from sheet name to get column name
    if column_name in distribution_plot_list:
        workbook.create_sheet(column_name + " distribution", sheet_number+1)
        worksheet = workbook.worksheets[sheet_number+1]
        image_path = tempdir_path / (column_name + ".distribution.png")
        logger.info(f"Adding {image_path} to {output_file} after sheet {sheet_name} ...")
        image = openpyxl.drawing.image.Image(image_path)
        image.anchor = "A1"
        worksheet.add_image(image)
        sheet_number += 1

# Size bar columns for the worksheets showing the ranks of values and patterns
for i, sheet_name in enumerate(workbook.sheetnames):
    if sheet_name.endswith("detail") or sheet_name.endswith("pattern"):
        worksheet = workbook.worksheets[i]
        for row_number in range(2, worksheet.max_row+1):
            value_to_convert = worksheet[f'D{row_number}'].value  # C = 3rd column, convert from percentage
            bar_representation = "█" * round(value_to_convert)
            worksheet[f'E{row_number}'] = bar_representation
        # And set some visual formatting while we are here
        worksheet.column_dimensions['B'].width = 25
        # worksheet.column_dimensions['C'].number_format = "0.0"

# Formatting for the summary sheet
worksheet = workbook.worksheets[0]
worksheet.column_dimensions['A'].width = 25  # Column names
worksheet.column_dimensions['G'].width = 15  # Most common value
worksheet.column_dimensions['I'].width = 15  # Largest value
worksheet.column_dimensions['J'].width = 15  # Smallest value
worksheet.column_dimensions['K'].width = 15  # Longest value

for row in range(1, worksheet.max_row+1):
    worksheet.cell(row=row, column=1).alignment = Alignment(horizontal='right')
for row in range(1, worksheet.max_row+1):
    for col in range(1, 17):
        worksheet.cell(row=row, column=col).border = Border(outline=Side(border_style=borders.BORDER_THICK, color='FFFFFFFF'))

workbook.save(output_file)
logger.info(f"Wrote {os.stat(output_file).st_size} bytes to '{output_file}'.")
