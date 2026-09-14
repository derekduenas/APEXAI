"""Offline connector CSV decoding. No authentication, network or pagination guesses."""
import csv
import hashlib
import io
import math
import re

from apex.intraday.massive import MassiveDataError

VERSION = 'MASSIVE_CONNECTOR_CSV_V1'
INTEGER = {'t', 'n', 'sip_timestamp', 'sequence_number', 'bid_size', 'ask_size',
           'bid_exchange', 'ask_exchange'}
NUMBER = {'o', 'h', 'l', 'c', 'v', 'vw', 'bid_price', 'ask_price',
          'strike_price', 'shares_per_contract'}
REQUIRED = {
    'bars': {'t', 'o', 'h', 'l', 'c', 'v'},
    'nbbo': {'sip_timestamp', 'sequence_number', 'bid_price', 'ask_price'},
    'chain': {'ticker', 'underlying_ticker', 'expiration_date', 'strike_price', 'contract_type'},
}


def decode_csv(text, *, family, max_rows=50000):
    """Return typed rows plus transport evidence; caller must validate/admit rows.

    Pagination and vendor metadata are unknown when absent from this CSV.
    The original text must be preserved by the caller. No vendor JSON response
    is manufactured, and nanosecond integers never pass through float.
    """
    if family not in REQUIRED or not isinstance(text, str):
        raise MassiveDataError('CONNECTOR_INPUT_INVALID')
    if type(max_rows) is not int or max_rows < 1:
        raise MassiveDataError('CONNECTOR_ROW_BOUND_INVALID')
    reader = csv.reader(io.StringIO(text), strict=True)
    try:
        header = next(reader)
        if len(header) != len(set(header)) or not REQUIRED[family] <= set(header):
            raise MassiveDataError('CONNECTOR_HEADER_INVALID')
        rows = []
        for fields in reader:
            if len(fields) != len(header):
                raise MassiveDataError('CONNECTOR_ROW_WIDTH_INVALID')
            if len(rows) >= max_rows:
                raise MassiveDataError('CONNECTOR_ROW_LIMIT')
            row = {}
            for key, value in zip(header, fields):
                if key in INTEGER:
                    if not re.fullmatch(r'[0-9]+', value):
                        raise MassiveDataError('CONNECTOR_INTEGER_INVALID:' + key)
                    row[key] = int(value)
                elif key in NUMBER:
                    try:
                        row[key] = float(value)
                    except ValueError as exc:
                        raise MassiveDataError('CONNECTOR_NUMBER_INVALID:' + key) from exc
                    if not math.isfinite(row[key]):
                        raise MassiveDataError('CONNECTOR_NUMBER_NONFINITE:' + key)
                else:
                    row[key] = value
            rows.append(row)
    except (csv.Error, StopIteration) as exc:
        raise MassiveDataError('CONNECTOR_CSV_MALFORMED') from exc
    return {'rows': rows, 'transport_version': VERSION,
            'payload_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
            'source_attribution': 'UNVERIFIED', 'pagination_status': 'UNKNOWN',
            'vendor_response_metadata': 'NOT_PRESENT_IN_CSV',
            'evaluation_ready': False}
