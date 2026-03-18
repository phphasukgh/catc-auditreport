from shared_utils.catc_restapi_lib import CatcRestApiClient
from shared_utils.log_setup import log_setup
from shared_utils.util import csv_to_dict, dict_to_csv, list_dict_to_csv, print_csv
from catc_config import CATC_IP, CATC_PORT
import logging
import json
import argparse
from argparse import RawTextHelpFormatter
import getpass
import time
import re
import logging


def main():
    log_setup(
        log_level=logging.DEBUG,
        log_file='logs/application_run.log',
        log_term=False,
        max_bytes=50*1024*1024  # 50MB
    )
    logging.info('starting the program.')
    
    print('='*20)
    username = input('Username: ')
    password = getpass.getpass()
    print('='*20)
    catc = CatcRestApiClient(CATC_IP, CATC_PORT, username, password)
    catc.logout()


if __name__ == '__main__':
    main()
