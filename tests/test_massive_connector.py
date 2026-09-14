import pytest
from apex.intraday.massive import MassiveDataError
from apex.intraday.massive_connector import decode_csv


def test_nanoseconds_remain_exact_and_absent_metadata_stays_unknown():
    r = decode_csv('sip_timestamp,sequence_number,bid_price,ask_price\n1789133400123456789,1,2,3\n', family='nbbo')
    assert r['rows'][0]['sip_timestamp'] == 1789133400123456789
    assert r['pagination_status'] == 'UNKNOWN'
    assert r['evaluation_ready'] is False


@pytest.mark.parametrize('body', [
    't,o,h,l,c,v\n1,2,3,1,2,NaN\n',
    't,o,h,l,c,v\n1,2,3,1,2,4,extra\n',
    't,o,h,l,c,v\n1,2,3,1,2\n',
    't,o,h,l,c,v,t\n1,2,3,1,2,4,1\n',
    't,o,h,l,c,v\n1.0,2,3,1,2,4\n',
])
def test_refuses_corruption(body):
    with pytest.raises(MassiveDataError):
        decode_csv(body, family='bars')


def test_bound_and_fractional_volume():
    body = 't,o,h,l,c,v\n1,2,3,1,2,4.25\n'
    assert decode_csv(body, family='bars')['rows'][0]['v'] == 4.25
    with pytest.raises(MassiveDataError, match='ROW_LIMIT'):
        decode_csv(body + '2,2,3,1,2,4\n', family='bars', max_rows=1)
