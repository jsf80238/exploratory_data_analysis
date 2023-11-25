import sys
from dataclasses import dataclass
import enum
import logging
import os
from pathlib import Path
from random import choices
import re
from string import ascii_lowercase
import tempfile
import types
from typing import Union, Optional, Type, Tuple
import unicodedata
# Imports above are standard Python
# Imports below are 3rd-party
import pendulum
import jaydebeapi as jdbc
from yaml import load, dump
try:
    from yaml import CLoader as Loader, CDumper as Dumper
except ImportError:
    from yaml import Loader, Dumper

min_major, min_minor = 3, 11
major, minor = sys.version_info[:2]
if major < min_major or minor < min_minor:
    raise Exception(f"Your Python version needs to be at least {min_major}.{min_minor}.")

old_factory = logging.getLogRecordFactory()


class Config:
    PRIMARY_CONFIG_FILE = "config.yaml"

    @classmethod
    def get_config(cls, file_name: str = PRIMARY_CONFIG_FILE) -> dict:
        """
        Read a configuration file from the configuration file directory
        :param file_name: file within the configuration directory
        :return: the configuration corresponding to that file
        """
        config_dir = Path(__file__).parent.parent.parent / "config"
        if not file_name.lower().endswith(".yaml"):
            file_name += ".yaml"
        config_file = config_dir / file_name
        text = open(config_file).read()
        return load(text, Loader=Loader)


class C(enum.StrEnum):
    BLACK_SQUARE = unicodedata.lookup("BLACK SQUARE")  # ■, x25A0
    CSV_EXTENSION = ".csv"
    SQL_EXTENSION = ".sql"
    EXCEL_EXTENSION = ".xlsx"
    CHAR = "CHAR"
    DATE = "DATE"
    DECIMAL = "DECIMAL"
    FLOAT = "FLOAT"
    NUMBER = "NUMBER"
    VARCHAR = "VARCHAR"
    DATABASE = "database"


config_dict = Config.get_config()
jar_file = config_dict[C.DATABASE]["jar_file"]
if sys.platform in ("linux", "darwin"):
    path_separator = ":"
elif sys.platform in ("win32", ):
    path_separator = ";"
else:
    raise Exception(f"Unexpected platform '{sys.platform}'.")
os.environ["CLASSPATH"] = os.environ.get("CLASSPATH", "") + path_separator + (Path(__file__).parent / jar_file).as_posix()
class_name = config_dict[C.DATABASE]["class_name"]
# database_name = config_dict[C.DATABASE]["database_name"]
port_number = config_dict[C.DATABASE]["port_number"]
# database_host = config_dict[C.DATABASE]["host_name"]
jdbc_path = config_dict[C.DATABASE]["jdbc_path"]


class Logger:
    level = None
    session = None
    logger = None

    @classmethod
    def get_logger(
       cls,
       level: [str|int] = None,
       session: str = None,
    ):
        """
        Return the same logger for every invocation.
        Includes a session to help with correlation. By default it's a random 6-character string.
        """
        if session:
            cls.session = session
        elif not cls.session:
            cls.session = ''.join(choices(ascii_lowercase, k=6))
        if not cls.logger:
            if level:
                cls.level = level.upper()
            if not cls.level:
                config_dict = Config.get_config()
                cls.level = config_dict["logging"]["level"]


            cls.logger = logging.getLogger()
            # Add session identifier
            logging.setLogRecordFactory(cls.record_factory_factory(cls.session))
            # Set overall logging level, will be overridden by the handlers
            cls.logger.setLevel(logging.DEBUG)
            # Formatting
            date_format = '%Y-%m-%dT%H:%M:%S%z'
            formatter = logging.Formatter('%(asctime)s | %(levelname)8s | session=%(session)s | %(message)s', datefmt=date_format)
            # Logging to STDERR
            console_handler = logging.StreamHandler()
            console_handler.setLevel(cls.level)
            console_handler.setFormatter(formatter)
            # Add console handler to logger
            cls.logger.addHandler(console_handler)
            # Optional DB logging handler
            if config_dict.get("logging").get("log_to_database"):
                db_handler = Logger.LogDBHandler()
                db_handler.setLevel(cls.level)
                # No formatting required here
                cls.logger.addHandler(db_handler)
        # Check to see if this invocation requested a particular logging level
        if level:
            for handler in cls.logger.handlers:
                handler.setLevel(level)
        # Check to see if this invocation requested a new session key
        if session:
            logging.setLogRecordFactory(cls.record_factory_factory(cls.session))
        return cls.logger


class Database:
    """
    Wrapper around the jaydebeapi module.
    """
    database_connection = None
    host_name = get_secret_value("applicationdatabasehostname")
    database_name = get_secret_value("applicationdatabasedatabasename")
    user_name = get_secret_value("applicationdatabaseusername")
    password = get_secret_value("applicationdatabasepassword")
    timeout = config_dict[C.DATABASE]["timeout"]
    connect_string = ""

    def __init__(self, auto_commit: bool = False):
        self.logger = Logger.get_logger()
        self.logger.info(f"Connecting to '{self.database_name} as {self.user_name}' ...")
        self.database_connection = jdbc.connect(class_name, self.connect_string, [self.user_name, self.password], jdbc_path)
        self.logger.info("... connected.")
        self.database_connection.jconn.setAutoCommit(auto_commit)

    def __enter__(self) -> jdbc.Connection:
        return self

    def __exit__(self, exception_type: Optional[Type[BaseException]],
                 exception_value: Optional[BaseException],
                 traceback: Optional[types.TracebackType]) -> bool:
        if exception_type is None:
            self.logger.info("Committing database actions ...")
            self.database_connection.commit()
            self.logger.info("... committed.")
        else:
            self.database_connection.rollback()
            self.logger.error(str(traceback))
        self.database_connection.close()
        return False

    def get_connection(self) -> jdbc.Connection:
        return self.database_connection

    def set_auto_commit(self, setting: bool) -> None:
        self.database_connection.jconn.setAutoCommit(setting)

    def execute(self,
            sql: str,
            parameters: list = list(),
            cursor: jdbc.Cursor = None,
            is_debug: bool = False,
            ) -> Tuple[jdbc.Cursor, list]:
        """
        Wrapper around the Cursor class

        :param sql: the query to be executed
        :param parameters: the parameters to fill the placeholders
        :param cursor: if provided will be used, else will create a new one
        :param is_debug: if True log the query but don't do anything
        :param is_commit: if True issue a database commit after (makes sense only for insert/update/delete)
        :return: a tuple containing:
        | 1: the cursor with the result set
        | 2: a list of the column names in the result set, or an empty list if not a SELECT statement
        """
        # Gather information about the caller so we can log a useful message
        # Search the stack for the first file which is not this one (that will be the caller we are interested in)
        for frame_info in stack():
            if frame_info.filename != __file__:
                identification = f"From directly above line {frame_info.lineno} in file {Path(frame_info.filename).name}"
                break
        else:
            identification = "<unknown>"
        # Format the SQL to fit on one line
        formatted_sql = re.sub(r"\s+", " ", sql).strip()
        # Make a cursor if one was not supplied by the caller
        if not cursor:
            cursor = self.database_connection.cursor()
        # Log the statement with the parameters converted to their passed values
        sql_for_logging = sql
        pattern = re.compile(r"\s*=\s*\?")
        needed_parameter_count = pattern.findall(sql)
        if len(needed_parameter_count) != len(parameters):
            self.logger.warning(f"I think the query contains {len(needed_parameter_count)} placeholders and I was given {len(parameters)} parameters: {parameters}")
        for param in parameters:
            if type(param) == str:
                param = "'" + param + "'"
            elif type(param) == int:
                param = str(param)
            else:
                self.logger.warning("Cannot log SQL, sorry.")
                break
            sql_for_logging = re.sub(pattern, " = " + param, sql_for_logging, 1)
        # Format the SQL to fit on one line
        sql_for_logging = re.sub(r"\s+", " ", sql_for_logging).strip()
        if is_debug:
            self.logger.info(f"{identification} would have executed: {sql_for_logging}.")
            return cursor, list()
        # Not merely debugging, try to execute and return results
        self.logger.info(f"{identification} executing: {sql_for_logging} ...")
        try:
            cursor.execute(sql, parameters)
        except Exception as e:
            self.logger.error(e)
            raise e
        # Successfully executed, now return a list of the column names
        try:
            column_list = [column[0] for column in cursor.description]
        except TypeError:  # For DML statements there will be no column description returned
            column_list = list()
            self.logger.info(f"Rows affected: {cursor.rowcount:,d}.")
        return cursor, column_list

    def fetch_one_row(self,
        sql: str,
        parameters: list = list(),
        default_value=None
        ) -> Union[list, str, int]:
        """
        Run the given query and fetch the first row.

        :param sql: the query to be executed
        :param parameters: the parameters to fill the placeholders
        :param default_value: if the query does not return any rows, return this.
        :return: if the return contains two or more things return them as a list, else return a single item.
        | If default_value not provided then ...
        | If there is only a single element in the select clause the function returns None.
        | If there are multiple elements in the select clause the function to return [None]*the number of elements.
        """
        cursor, column_list = self.execute(sql, parameters)
        for row in cursor.fetchall():
            if len(row) == 1:
                return row[0]
            else:
                return row
            break
        self.logger.info("No rows selected.")
        if default_value:
            return default_value
        else:
            if len(column_list) == 1:
                return None
            else:
                return [None]*len(column_list)

    def commit(self) -> None:
        """
        Call get_connection().commit().
        """
        self.get_connection().commit()


def dedent_sql(s):
    """
    Remove leading spaces from all lines of a SQL query.

    :param s: query
    :return: cleaned-up version of query
    """
    return "\n".join([x.lstrip() for x in s.splitlines()])


def get_line_count(file_path: Union[str, Path]) -> int:
    """
    See https://stackoverflow.com/questions/845058/how-to-get-line-count-of-a-large-file-cheaply-in-python
    """
    f = open(file_path, 'rb')
    line_count = 0
    buf_size = 1024 * 1024
    read_f = f.raw.read

    buf = read_f(buf_size)
    while buf:
        line_count += buf.count(b'\n')
        buf = read_f(buf_size)

    return line_count


if __name__ == "__main__":
    logger = Logger.get_logger()
    logger.info("a logging message")
    mydb = Database()
    query = """
        SELECT 1
        """
    print(mydb.fetch_one_row(query, parameters=['STD', 'OCT']))
    exit()
