import os
import re
import csv
import json
import pytest
import tempfile
import threading
import platform
from unittest.mock import patch, MagicMock, mock_open
from time import time

from zefoy_bot import (
    decode, http_request, validate_tiktok_url, validate_captcha_page,
    parse_captcha_fields, create_session, parse_timer, wait_timer,
    check_service_status, build_multipart, extract_key_from_html,
    extract_service_form, send_action, search_link, show_services,
    set_window_title, format_number, log_cycle, init_csv,
    SERVICES, DEBUG_DIR, CSV_FILE, CSV_LOCK, ZEFOY_URL,
    CONFIG, AdaptiveRateLimiter, ProxyHealthChecker, JsonFormatter,
    input_with_timeout, supports_ansi, clear_screen,
    save_config, load_config,
)


# ============================================================
# decode
# ============================================================

def test_decode_valid():
    import base64
    from urllib.parse import quote
    original = b'hello world'
    encoded = quote(base64.b64encode(original).decode())[::-1]
    assert decode(encoded) == 'hello world'


def test_decode_empty_string():
    with pytest.raises(ValueError, match='Empty text'):
        decode('')


def test_decode_invalid_base64():
    with pytest.raises(ValueError, match='Decode failed'):
        decode('not_base64_!!!')


def test_decode_zefoy_format():
    import base64
    from urllib.parse import quote
    payload = '{"timer":"Please wait 30 seconds"}'
    encoded = quote(base64.b64encode(payload.encode()).decode())[::-1]
    assert decode(encoded) == payload


# ============================================================
# extract_key_from_html
# ============================================================

def test_extract_key_remove_spaces():
    html = 'remove-spaces" name="abc123" placeholder="Enter answer"'
    assert extract_key_from_html(html) == 'abc123'


def test_extract_key_name_value():
    html = 'name="mykey" value="something"'
    assert extract_key_from_html(html) == 'mykey'


def test_extract_key_token_param():
    html = 'key=xyz789'
    assert extract_key_from_html(html) == 'xyz789'


def test_extract_key_skips_token():
    html = 'name="token" value="x"'
    assert extract_key_from_html(html) is None


def test_extract_key_long_key():
    html = 'name="' + 'x' * 200 + '"'
    assert extract_key_from_html(html) is None


def test_extract_key_none():
    assert extract_key_from_html('no keys here') is None


def test_extract_key_field_name_pattern():
    html = '<input class="remove-spaces" name="2b8882fa4049" placeholder="Enter Video URL">'
    assert extract_key_from_html(html) == '2b8882fa4049'


# ============================================================
# validate_tiktok_url
# ============================================================

def test_validate_tiktok_url_valid():
    assert validate_tiktok_url('https://vm.tiktok.com/ZN81MaJ7k/') is True


def test_validate_tiktok_url_www():
    assert validate_tiktok_url('https://www.tiktok.com/@user/video/123') is True


def test_validate_tiktok_url_vt():
    assert validate_tiktok_url('https://vt.tiktok.com/abc123/') is True


def test_validate_tiktok_url_no_scheme():
    assert validate_tiktok_url('vm.tiktok.com/ZN81MaJ7k/') is False


def test_validate_tiktok_url_wrong_host():
    assert validate_tiktok_url('https://youtube.com/watch?v=123') is False


def test_validate_tiktok_url_empty():
    assert validate_tiktok_url('') is False


def test_validate_tiktok_url_none():
    assert validate_tiktok_url(None) is False


def test_validate_tiktok_url_no_path():
    assert validate_tiktok_url('https://tiktok.com') is False


# ============================================================
# create_session
# ============================================================

def test_create_session_has_headers():
    session = create_session()
    assert 'user-agent' in session.headers


def test_create_session_is_requests_session():
    import requests
    session = create_session()
    assert isinstance(session, requests.Session)


def test_create_session_with_proxy():
    session = create_session(proxy='http://1.2.3.4:8080')
    assert session.proxies.get('http') == 'http://1.2.3.4:8080'
    assert session.proxies.get('https') == 'http://1.2.3.4:8080'


def test_create_session_socks5_proxy():
    session = create_session(proxy='socks5://1.2.3.4:1080')
    assert session.proxies.get('http') == 'socks5://1.2.3.4:1080'


# ============================================================
# validate_captcha_page
# ============================================================

def test_validate_captcha_page_search_input():
    html = '<input type="search" name="captchalogin" maxlength="30">' + 'x' * 2000
    assert validate_captcha_page(html) is True


def test_validate_captcha_page_img_id():
    html = '<img id="captcha-img" src="/cap.png"><input name="captchalogin">' + 'x' * 2000
    assert validate_captcha_page(html) is True


def test_validate_captcha_page_empty():
    assert validate_captcha_page('') is False


def test_validate_captcha_page_none():
    assert validate_captcha_page(None) is False


def test_validate_captcha_page_safety_notice():
    html = 'Important Official Zefoy Notice' + 'x' * 2000
    assert validate_captcha_page(html) is False


def test_validate_captcha_page_no_form():
    html = '<html>' + 'x' * 2000 + '</html>'
    assert validate_captcha_page(html) is False


# ============================================================
# parse_captcha_fields
# ============================================================

def test_parse_search_input():
    html = '<input type="search" name="captchalogin" maxlength="30">'
    inputs, hidden, img = parse_captcha_fields(html)
    assert len(inputs) > 0
    assert 'captchalogin' in str(inputs)


def test_parse_text_input():
    html = '<input type="text" name="captcha_field" value="test123">'
    inputs, hidden, img = parse_captcha_fields(html)
    assert len(inputs) > 0


def test_parse_hidden_captchaencoded():
    html = '<input type="hidden" name="captchaencoded" value="abc123">'
    inputs, hidden, img = parse_captcha_fields(html)
    assert len(hidden) > 0


def test_parse_captcha_img_id():
    html = '<img id="captcha-img" src="/assets/captcha.png">'
    inputs, hidden, img = parse_captcha_fields(html)
    assert img is not None
    assert 'captcha.png' in img


def test_parse_captcha_img_empty_src():
    html = '<img id="captcha-img" src="">'
    inputs, hidden, img = parse_captcha_fields(html)
    assert img is None or img == ''


def test_parse_full_page():
    html = '<input type="hidden" name="captchaencoded" value="xyz"><input type="search" name="captchalogin" maxlength="30"><img id="captcha-img" src="/cap.png">'
    inputs, hidden, img = parse_captcha_fields(html)
    assert len(inputs) > 0
    assert len(hidden) > 0
    assert img is not None


def test_parse_no_fields():
    html = '<html><body>No form</body></html>'
    inputs, hidden, img = parse_captcha_fields(html)
    assert inputs == []
    assert hidden == []
    assert img is None


# ============================================================
# http_request
# ============================================================

@patch('zefoy_bot.sleep', return_value=None)
def test_http_request_success(mock_sleep):
    session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    session.request.return_value = mock_resp
    resp = http_request(session, 'GET', 'https://example.com')
    assert resp.status_code == 200


@patch('zefoy_bot.sleep', return_value=None)
def test_http_request_retries_429(mock_sleep):
    session = MagicMock()
    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_ok = MagicMock()
    resp_ok.status_code = 200
    session.request.side_effect = [resp_429, resp_ok]
    resp = http_request(session, 'GET', 'https://example.com', max_retries=3)
    assert resp.status_code == 200
    assert session.request.call_count == 2


@patch('zefoy_bot.sleep', return_value=None)
def test_http_request_retries_500(mock_sleep):
    session = MagicMock()
    resp_500 = MagicMock()
    resp_500.status_code = 500
    resp_ok = MagicMock()
    resp_ok.status_code = 200
    session.request.side_effect = [resp_500, resp_ok]
    resp = http_request(session, 'GET', 'https://example.com', max_retries=3)
    assert resp.status_code == 200


@patch('zefoy_bot.sleep', return_value=None)
def test_http_request_gives_up(mock_sleep):
    session = MagicMock()
    resp_429 = MagicMock()
    resp_429.status_code = 429
    session.request.return_value = resp_429
    with pytest.raises(Exception, match='Failed after'):
        http_request(session, 'GET', 'https://example.com', max_retries=2)


@patch('zefoy_bot.sleep', return_value=None)
def test_http_request_timeout_retries(mock_sleep):
    from requests.exceptions import Timeout
    session = MagicMock()
    session.request.side_effect = [Timeout(), MagicMock(status_code=200)]
    resp = http_request(session, 'GET', 'https://example.com', max_retries=3)
    assert resp.status_code == 200


@patch('zefoy_bot.sleep', return_value=None)
def test_http_request_connection_error_retries(mock_sleep):
    from requests.exceptions import ConnectionError
    session = MagicMock()
    session.request.side_effect = [ConnectionError(), MagicMock(status_code=200)]
    resp = http_request(session, 'GET', 'https://example.com', max_retries=3)
    assert resp.status_code == 200


# ============================================================
# parse_timer
# ============================================================

def test_parse_timer_ltm():
    assert parse_timer('var ltm=120;') == 120


def test_parse_timer_ltm_zero():
    assert parse_timer('var ltm=0;') == 0


def test_parse_timer_min_sec():
    assert parse_timer('Please wait 3 minutes 45 seconds') == 225


def test_parse_timer_seconds():
    assert parse_timer('Please wait 90 seconds') == 90


def test_parse_timer_none():
    assert parse_timer('<html>no timer</html>') == 0


def test_parse_timer_in_html():
    html = '<span>Please wait 73 seconds before trying again.</span>'
    assert parse_timer(html) == 73


def test_parse_timer_minute_only():
    assert parse_timer('Please wait 2 minutes 30 seconds') == 150


# ============================================================
# wait_timer
# ============================================================

@patch('zefoy_bot.sleep', return_value=None)
def test_wait_timer_short(mock_sleep):
    wait_timer(2)
    assert mock_sleep.call_count >= 1


def test_wait_timer_zero():
    wait_timer(0)
    wait_timer(-5)


# ============================================================
# check_service_status
# ============================================================

def test_service_enabled():
    html = '<button class="btn btn-primary t-views-button">Views</button>'
    assert check_service_status(html, 't-views-button') is True


def test_service_disabled():
    html = '<button disabled class="btn btn-primary t-views-button">Views</button>'
    assert check_service_status(html, 't-views-button') is False


def test_service_not_found():
    html = '<div class="other">X</div>'
    assert check_service_status(html, 't-views-button') is False


def test_service_disabled_in_class():
    html = '<button class="t-views-button off">Views</button>'
    assert check_service_status(html, 't-views-button') is False


def test_service_with_form_enabled():
    html = '<div class="t-chearts-menu"><form><input></form></div>'
    assert check_service_status(html, 't-chearts-button') is True


# ============================================================
# build_multipart
# ============================================================

def test_build_multipart():
    body, boundary = build_multipart('key', 'value')
    assert 'key' in body
    assert 'value' in body
    assert boundary.startswith('----WebKitFormBoundary')


def test_build_multipart_unique():
    _, b1 = build_multipart('k', 'v')
    _, b2 = build_multipart('k', 'v')
    assert b1 != b2


def test_build_multipart_escapes_newlines():
    body, _ = build_multipart('key', 'value\r\ninjected\r\n--boundary--')
    assert '\r\ninjected\r\n--boundary--' not in body
    assert 'valueinjected--boundary--' in body


def test_build_multipart_escapes_null():
    body, _ = build_multipart('key', 'value\x00test')
    assert '\x00' not in body
    assert 'valuetest' in body


# ============================================================
# extract_service_form
# ============================================================

def test_extract_service_form_basic():
    html = '''
    <div class="col-sm t-views-menu nonec">
    <div class="card">
    <form action="c2VuZC9mb2xeb3dlcnNfdGlrdG9V">
    <input name="2b8882fa4049" placeholder="Enter Video URL">
    </form>
    </div>
    </div>
    '''
    api_url, field_name = extract_service_form(html, 't-views-menu')
    assert api_url is not None
    assert 'c2VuZC9mb2xeb3dlcnNfdGlrdG9V' in api_url
    assert field_name == '2b8882fa4049'


def test_extract_service_form_not_found():
    html = '<div class="other-menu"></div>'
    api_url, field_name = extract_service_form(html, 't-views-menu')
    assert api_url is None
    assert field_name is None


# ============================================================
# set_window_title
# ============================================================

@patch('os.name', 'nt')
@patch('subprocess.run')
def test_set_window_title_safe(mock_run):
    set_window_title('Zefoy Bot | Views: 100')
    mock_run.assert_called_once()


@patch('os.name', 'nt')
@patch('subprocess.run')
def test_set_window_title_sanitized(mock_run):
    set_window_title('Test & title | command; injection')
    args = mock_run.call_args[0][0]
    title = args[-1]
    assert '&' not in title
    assert '|' not in title
    assert ';' not in title


# ============================================================
# format_number
# ============================================================

def test_format_number():
    assert format_number(1000) == '1.000'
    assert format_number(1234567) == '1.234.567'
    assert format_number(0) == '0'


# ============================================================
# init_csv / log_cycle
# ============================================================

def test_init_csv_creates_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_csv = os.path.join(tmpdir, 'test_stats.csv')
        import zefoy_bot
        old_csv = zefoy_bot.CSV_FILE
        zefoy_bot.CSV_FILE = test_csv
        try:
            init_csv()
            assert os.path.exists(test_csv)
            with open(test_csv, 'r') as f:
                reader = csv.reader(f)
                header = next(reader)
                assert 'timestamp' in header
                assert 'cycle' in header
        finally:
            zefoy_bot.CSV_FILE = old_csv


def test_init_csv_append_mode():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_csv = os.path.join(tmpdir, 'test_stats.csv')
        import zefoy_bot
        old_csv = zefoy_bot.CSV_FILE
        zefoy_bot.CSV_FILE = test_csv
        try:
            init_csv()
            log_cycle(1, True, 1, 10.0, 5)
            init_csv()
            with open(test_csv, 'r') as f:
                lines = f.readlines()
                assert len(lines) == 2, f'Expected 2 lines (header + 1 data), got {len(lines)}'
                assert lines[0].startswith('timestamp')
                assert not lines[1].startswith('timestamp'), 'Data row should not be a header'
        finally:
            zefoy_bot.CSV_FILE = old_csv


def test_log_cycle_writes_data():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_csv = os.path.join(tmpdir, 'test_stats.csv')
        import zefoy_bot
        old_csv = zefoy_bot.CSV_FILE
        zefoy_bot.CSV_FILE = test_csv
        try:
            init_csv()
            log_cycle(1, True, 5, 10.0, 30)
            with open(test_csv, 'r') as f:
                reader = csv.DictReader(f)
                row = next(reader)
                assert row['cycle'] == '1'
                assert row['success'] == '1'
                assert row['total_sent'] == '5'
        finally:
            zefoy_bot.CSV_FILE = old_csv


# ============================================================
# send_action (mocked)
# ============================================================

@patch('zefoy_bot.sleep', return_value=None)
@patch('zefoy_bot.decode')
@patch('zefoy_bot.http_request')
def test_send_action_success(mock_http, mock_decode, mock_sleep):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = 'encoded'
    mock_resp.url = 'https://zefoy.com/c2VuZC9mb2xsb3dlcnNfdGlrdG9r'
    mock_http.return_value = mock_resp
    mock_decode.return_value = 'views sent successfully'
    session = MagicMock()
    result = send_action(session, 'key', '12345', 'https://zefoy.com/c2VuZC9mb2xsb3dlcnNfdGlrdG9r')
    assert result is True


@patch('zefoy_bot.sleep', return_value=None)
@patch('zefoy_bot.decode')
@patch('zefoy_bot.http_request')
def test_send_action_redirect(mock_http, mock_decode, mock_sleep):
    mock_resp = MagicMock()
    mock_resp.status_code = 302
    mock_resp.text = ''
    mock_resp.headers = {'Location': 'https://zefoy.com/'}
    mock_http.return_value = mock_resp
    session = MagicMock()
    result = send_action(session, 'key', '12345', 'https://zefoy.com/api')
    assert result is False


@patch('zefoy_bot.sleep', return_value=None)
@patch('zefoy_bot.decode')
@patch('zefoy_bot.http_request')
def test_send_action_timer(mock_http, mock_decode, mock_sleep):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = 'Please wait 30 seconds'
    mock_resp.url = 'https://zefoy.com/api'
    mock_http.return_value = mock_resp
    session = MagicMock()
    result = send_action(session, 'key', '12345', 'https://zefoy.com/api')
    assert result is False


@patch('zefoy_bot.sleep', return_value=None)
@patch('zefoy_bot.decode')
@patch('zefoy_bot.http_request')
def test_send_action_session_expired(mock_http, mock_decode, mock_sleep):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = 'encoded'
    mock_resp.url = 'https://zefoy.com/api'
    mock_http.return_value = mock_resp
    mock_decode.return_value = 'Session expired'
    session = MagicMock()
    with pytest.raises(RuntimeError, match='Session expired'):
        send_action(session, 'key', '12345', 'https://zefoy.com/api')


@patch('zefoy_bot.sleep', return_value=None)
@patch('zefoy_bot.decode')
@patch('zefoy_bot.http_request')
def test_send_action_hearts_sent(mock_http, mock_decode, mock_sleep):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = 'encoded'
    mock_resp.url = 'https://zefoy.com/api'
    mock_http.return_value = mock_resp
    mock_decode.return_value = 'hearts sent successfully'
    session = MagicMock()
    result = send_action(session, 'key', '12345', 'https://zefoy.com/api')
    assert result is True


@patch('zefoy_bot.sleep', return_value=None)
@patch('zefoy_bot.decode')
@patch('zefoy_bot.http_request')
def test_send_action_fcde_form_success(mock_http, mock_decode, mock_sleep):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = 'encoded'
    mock_resp.url = 'https://zefoy.com/c2VuZC9mb2xsb3dlcnNfdGlrdG9r'
    mock_http.return_value = mock_resp
    mock_decode.return_value = '<form action="w1a" onsubmit="fcde(\'.w1a\',\'.w2a\')">'
    session = MagicMock()
    result = send_action(session, 'key', '12345', 'https://zefoy.com/c2VuZC9mb2xsb3dlcnNfdGlrdG9r')
    assert result is True


@patch('zefoy_bot.sleep', return_value=None)
@patch('zefoy_bot.decode')
@patch('zefoy_bot.http_request')
def test_send_action_showhide_form_success(mock_http, mock_decode, mock_sleep):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = 'encoded'
    mock_resp.url = 'https://zefoy.com/c2VuZC9mb2xsb3dlcnNfdGlrdG9r'
    mock_http.return_value = mock_resp
    mock_decode.return_value = '<form action="w1r" onsubmit="showHideElements(\'.w1r\',\'.w2r\')">'
    session = MagicMock()
    result = send_action(session, 'key', '12345', 'https://zefoy.com/c2VuZC9mb2xsb3dlcnNfdGlrdG9r')
    assert result is True


@patch('zefoy_bot.sleep', return_value=None)
@patch('zefoy_bot.decode')
@patch('zefoy_bot.http_request')
def test_send_action_decode_fail(mock_http, mock_decode, mock_sleep):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = 'garbage'
    mock_resp.url = 'https://zefoy.com/api'
    mock_http.return_value = mock_resp
    mock_decode.side_effect = ValueError('Decode failed')
    session = MagicMock()
    result = send_action(session, 'key', '12345', 'https://zefoy.com/api')
    assert result is False


@patch('zefoy_bot.sleep', return_value=None)
@patch('zefoy_bot.http_request')
def test_send_action_request_error(mock_http, mock_sleep):
    import requests
    mock_http.side_effect = requests.RequestException('fail')
    session = MagicMock()
    result = send_action(session, 'key', '12345', 'https://zefoy.com/api')
    assert result is False


# ============================================================
# search_link (mocked)
# ============================================================

@patch('zefoy_bot.sleep', return_value=None)
@patch('zefoy_bot.decode')
@patch('zefoy_bot.http_request')
def test_search_link_timer_retry(mock_http, mock_decode, mock_sleep):
    timer_resp = MagicMock()
    timer_resp.status_code = 200
    timer_resp.text = 'Please wait 73 seconds'
    timer_resp.url = 'https://zefoy.com/api'
    mock_http.return_value = timer_resp

    form_resp = MagicMock()
    form_resp.status_code = 200
    form_resp.text = 'encoded'
    form_resp.url = 'https://zefoy.com/api'
    mock_http.return_value = form_resp
    mock_decode.return_value = 'onsubmit="showHideElements" name="token" value="aweme123" hidden'

    session = MagicMock()
    with patch('zefoy_bot.wait_timer'):
        result = search_link(session, 'key', 'https://vm.tiktok.com/abc', 'https://zefoy.com/api', max_retries=3)


@patch('zefoy_bot.sleep', return_value=None)
@patch('zefoy_bot.decode')
@patch('zefoy_bot.http_request')
def test_search_link_redirect_continues(mock_http, mock_decode, mock_sleep):
    mock_resp = MagicMock()
    mock_resp.status_code = 302
    mock_resp.text = ''
    mock_resp.headers = {'Location': 'https://zefoy.com/'}
    mock_http.return_value = mock_resp

    form_resp = MagicMock()
    form_resp.status_code = 200
    form_resp.text = 'encoded'
    form_resp.url = 'https://zefoy.com/api'
    mock_http.return_value = form_resp
    mock_decode.return_value = 'onsubmit="showHideElements" name="token" value="aweme123" hidden'

    session = MagicMock()
    result = search_link(session, 'key', 'https://vm.tiktok.com/abc', 'https://zefoy.com/api', max_retries=3)


@patch('zefoy_bot.sleep', return_value=None)
@patch('zefoy_bot.decode')
@patch('zefoy_bot.http_request')
def test_search_link_session_expired(mock_http, mock_decode, mock_sleep):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = 'homepage'
    mock_resp.url = 'https://zefoy.com/'
    mock_http.return_value = mock_resp

    session = MagicMock()
    with pytest.raises(RuntimeError, match='Session expired'):
        search_link(session, 'key', 'https://vm.tiktok.com/abc', 'https://zefoy.com/api', max_retries=1)


@patch('zefoy_bot.sleep', return_value=None)
@patch('zefoy_bot.decode')
@patch('zefoy_bot.http_request')
def test_search_link_decode_fail_retries(mock_http, mock_decode, mock_sleep):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = 'garbage'
    mock_resp.url = 'https://zefoy.com/api'
    mock_http.return_value = mock_resp
    mock_decode.side_effect = ValueError('Decode failed')

    form_resp = MagicMock()
    form_resp.status_code = 200
    form_resp.text = 'encoded'
    form_resp.url = 'https://zefoy.com/api'
    mock_http.return_value = form_resp
    mock_decode.side_effect = None
    mock_decode.return_value = 'onsubmit="showHideElements" name="token" value="aweme123" hidden'

    session = MagicMock()
    result = search_link(session, 'key', 'https://vm.tiktok.com/abc', 'https://zefoy.com/api', max_retries=3)


@patch('zefoy_bot.sleep', return_value=None)
@patch('zefoy_bot.decode')
@patch('zefoy_bot.http_request')
def test_search_link_fcde_form(mock_http, mock_decode, mock_sleep):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = 'encoded'
    mock_resp.url = 'https://zefoy.com/api'
    mock_http.return_value = mock_resp
    mock_decode.return_value = '<form onsubmit="fcde()"><input type="hidden" name="field" value="aweme456"></form>'

    session = MagicMock()
    with patch('zefoy_bot.send_action', return_value=True) as mock_send:
        result = search_link(session, 'key', 'https://vm.tiktok.com/abc', 'https://zefoy.com/api', max_retries=1)
        assert result is True
        mock_send.assert_called_once()


@patch('zefoy_bot.sleep', return_value=None)
@patch('zefoy_bot.decode')
@patch('zefoy_bot.http_request')
def test_search_link_request_error(mock_http, mock_decode, mock_sleep):
    import requests
    mock_http.side_effect = requests.RequestException('fail')
    session = MagicMock()
    result = search_link(session, 'key', 'https://vm.tiktok.com/abc', 'https://zefoy.com/api', max_retries=1)
    assert result is None


@patch('zefoy_bot.sleep', return_value=None)
@patch('zefoy_bot.decode')
@patch('zefoy_bot.http_request')
def test_search_link_no_form_no_timer(mock_http, mock_decode, mock_sleep):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = 'encoded'
    mock_resp.url = 'https://zefoy.com/api'
    mock_http.return_value = mock_resp
    mock_decode.return_value = 'some unknown response without form or timer'

    session = MagicMock()
    result = search_link(session, 'key', 'https://vm.tiktok.com/abc', 'https://zefoy.com/api', max_retries=2)
    assert result is None


# ============================================================
# SERVICES
# ============================================================

def test_services_count():
    assert len(SERVICES) == 8


def test_services_keys():
    for key, svc in SERVICES.items():
        assert 'name' in svc
        assert 'selector' in svc
        assert 'menu' in svc


def test_services_all_have_menu():
    for key, svc in SERVICES.items():
        assert svc['menu'].endswith('-menu')
        assert svc['selector'].endswith('-button')


# ============================================================
# Debug file analysis - integration tests
# ============================================================

def test_service_list_html_structure():
    debug_path = os.path.join(os.path.dirname(__file__), '..', 'debug', 'service_list.html')
    if os.path.exists(debug_path):
        with open(debug_path, 'r', encoding='utf-8') as f:
            html = f.read()
        assert 'zefoy.com' in html
        for num, svc in SERVICES.items():
            assert svc['menu'] in html or svc['selector'] in html


def test_cookie_verify_html_valid():
    debug_path = os.path.join(os.path.dirname(__file__), '..', 'debug', 'cookie_verify.html')
    if os.path.exists(debug_path):
        with open(debug_path, 'r', encoding='utf-8') as f:
            html = f.read()
        assert 'Zefoy' in html
        assert 'PHPSESSID' in html or 'cookie' in html.lower()


def test_search_link_unknown_html_form():
    debug_path = os.path.join(os.path.dirname(__file__), '..', 'debug', 'search_link_unknown.html')
    if os.path.exists(debug_path):
        with open(debug_path, 'r', encoding='utf-8') as f:
            html = f.read()
        assert len(html.strip()) > 0
    else:
        pytest.skip('search_link_unknown.html not found in debug/')


# ============================================================
# Edge cases
# ============================================================

def test_validate_tiktok_url_special_chars():
    assert validate_tiktok_url('https://vm.tiktok.com/ZN81MaJ7k/?x=1&y=2') is True


def test_decode_unicode():
    import base64
    from urllib.parse import quote
    payload = 'Ciao mondo - 你好世界'
    encoded = quote(base64.b64encode(payload.encode('utf-8')).decode())[::-1]
    assert decode(encoded) == payload


def test_build_multipart_large_value():
    large_value = 'x' * 10000
    body, boundary = build_multipart('key', large_value)
    assert large_value in body
    assert boundary in body


def test_parse_timer_negative():
    assert parse_timer('Please wait -5 seconds') == 0


def test_format_number_large():
    assert format_number(999999999) == '999.999.999'


@patch('zefoy_bot.sleep', return_value=None)
def test_http_request_respects_timeout(mock_sleep):
    session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    session.request.return_value = mock_resp
    http_request(session, 'GET', 'https://example.com', timeout=5)
    _, kwargs = session.request.call_args
    assert kwargs.get('timeout') == 5


def test_extract_service_form_fallback():
    html = '<div class="t-views-menu"><form action="c2VuZC9mb2xeb3dlcnNfdGlrdG9V"><input name="abc123def456"></form></div>'
    api_url, field = extract_service_form(html, 't-views-menu')
    assert api_url is not None
    assert field is not None


# ============================================================
# AdaptiveRateLimiter
# ============================================================

def test_rate_limiter_default_delay():
    limiter = AdaptiveRateLimiter(base_delay=5)
    assert limiter.get_delay() == 5


def test_rate_limiter_increases_on_429():
    limiter = AdaptiveRateLimiter(base_delay=5)
    limiter.record_status(200)
    limiter.record_status(200)
    limiter.record_status(429)
    assert limiter.get_delay() > 5


def test_rate_limiter_decreases_on_success():
    limiter = AdaptiveRateLimiter(base_delay=10, min_delay=1)
    for _ in range(10):
        limiter.record_status(200)
    assert limiter.get_delay() <= 10


def test_rate_limiter_respects_bounds():
    limiter = AdaptiveRateLimiter(base_delay=5, min_delay=2, max_delay=20)
    for _ in range(20):
        limiter.record_status(429)
    assert limiter.get_delay() <= 20
    for _ in range(50):
        limiter.record_status(200)
    assert limiter.get_delay() >= 2


# ============================================================
# ProxyHealthChecker
# ============================================================

def test_proxy_health_unknown_proxy_is_healthy():
    checker = ProxyHealthChecker()
    assert checker.is_healthy('1.2.3.4:8080') is True


def test_proxy_health_records_success():
    checker = ProxyHealthChecker()
    checker.record('1.2.3.4:8080', True)
    checker.record('1.2.3.4:8080', True)
    assert checker.is_healthy('1.2.3.4:8080') is True


def test_proxy_health_records_failure():
    checker = ProxyHealthChecker()
    for _ in range(10):
        checker.record('1.2.3.4:8080', False)
    assert checker.is_healthy('1.2.3.4:8080') is False


def test_proxy_health_mixed_results():
    checker = ProxyHealthChecker()
    for _ in range(2):
        checker.record('1.2.3.4:8080', True)
    for _ in range(8):
        checker.record('1.2.3.4:8080', False)
    assert checker.is_healthy('1.2.3.4:8080') is False


def test_proxy_health_get_best():
    checker = ProxyHealthChecker()
    for _ in range(5):
        checker.record('bad:80', False)
    checker.record('good:80', True)
    best = checker.get_best_proxy(['bad:80', 'good:80'])
    assert best == 'good:80'


# ============================================================
# JsonFormatter
# ============================================================

def test_json_formatter():
    import logging
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name='test', level=logging.INFO, pathname='', lineno=0,
        msg='test message', args=(), exc_info=None
    )
    output = formatter.format(record)
    import json
    data = json.loads(output)
    assert data['level'] == 'INFO'
    assert data['message'] == 'test message'
    assert 'time' in data


def test_json_formatter_with_exception():
    import logging
    import json
    formatter = JsonFormatter()
    try:
        raise ValueError('test error')
    except ValueError:
        import sys
        record = logging.LogRecord(
            name='test', level=logging.ERROR, pathname='', lineno=0,
            msg='error occurred', args=(), exc_info=sys.exc_info()
        )
    output = formatter.format(record)
    data = json.loads(output)
    assert data['level'] == 'ERROR'
    assert 'exception' in data
    assert 'ValueError' in data['exception']


# ============================================================
# Config
# ============================================================

def test_config_has_defaults():
    assert 'max_cycles' in CONFIG
    assert 'max_errors' in CONFIG
    assert 'request_timeout' in CONFIG
    assert 'target_views' in CONFIG
    assert 'max_threads' in CONFIG
    assert 'max_time_limit_hours' in CONFIG


def test_save_and_load_config(tmp_path):
    import json as json_mod
    config_path = str(tmp_path / 'test_config.json')
    test_config = {'max_cycles': 50, 'target_views': 5000}
    with open(config_path, 'w') as f:
        json_mod.dump(test_config, f)
    with patch('zefoy_bot.CONFIG_FILE', config_path):
        loaded = load_config()
    assert loaded['max_cycles'] == 50
    assert loaded['target_views'] == 5000
    assert loaded['max_errors'] == CONFIG['max_errors']


def test_save_config_roundtrip(tmp_path):
    import json as json_mod
    config_path = str(tmp_path / 'test_config.json')
    original = CONFIG.copy()
    original['max_cycles'] = 42
    with open(config_path, 'w') as f:
        json_mod.dump(original, f)
    with open(config_path, 'r') as f:
        loaded = json_mod.load(f)
    assert loaded['max_cycles'] == 42


# ============================================================
# supports_ansi / clear_screen
# ============================================================

def test_supports_ansi_returns_bool():
    result = supports_ansi()
    assert isinstance(result, bool)


def test_clear_screen_does_not_crash():
    clear_screen()


# ============================================================
# SQLiteStats
# ============================================================

def test_sqlite_stats_log_cycle(tmp_path):
    from zefoy_bot import SqliteStats
    db_path = str(tmp_path / 'test_stats.db')
    stats = SqliteStats(db_path)
    stats.log_cycle(1, True, 10, 60.0, 5, 0, 'Views')
    stats.log_cycle(2, False, 10, 120.0, 0, 0, 'Views')
    rows = stats.get_stats(service='Views')
    assert len(rows) == 2
    assert rows[0][3] == 0
    assert rows[1][3] == 1


def test_sqlite_stats_session_end(tmp_path):
    from zefoy_bot import SqliteStats
    db_path = str(tmp_path / 'test_stats.db')
    stats = SqliteStats(db_path)
    stats.log_session_end('Views', 100, 300.0)
    assert os.path.exists(db_path)


def test_sqlite_stats_last_n(tmp_path):
    from zefoy_bot import SqliteStats
    db_path = str(tmp_path / 'test_stats.db')
    stats = SqliteStats(db_path)
    for i in range(5):
        stats.log_cycle(i, True, i * 10, 60.0 * i, 0, 0, 'Views')
    rows = stats.get_stats(last_n=3)
    assert len(rows) == 3


# ============================================================
# parse_args
# ============================================================

def test_parse_args_defaults():
    import sys
    from zefoy_bot import parse_args
    with patch.object(sys, 'argv', ['zefoy_bot.py']):
        args = parse_args()
        assert args.url is None
        assert args.method is None
        assert args.threads is None
        assert args.service is None


def test_parse_args_with_url():
    import sys
    from zefoy_bot import parse_args
    with patch.object(sys, 'argv', ['zefoy_bot.py', '--url', 'https://vm.tiktok.com/test']):
        args = parse_args()
        assert args.url == 'https://vm.tiktok.com/test'


def test_parse_args_all_flags():
    import sys
    from zefoy_bot import parse_args
    with patch.object(sys, 'argv', ['zefoy_bot.py', '--url', 'https://vm.tiktok.com/test', '--method', '2',
                                     '--threads', '5', '--service', '6', '--time', '60',
                                     '--proxy', '1.2.3.4:8080', '--phpsessid', 'abc123',
                                     '--target', '50000', '--max-cycles', '100', '--json-log']):
        args = parse_args()
        assert args.url == 'https://vm.tiktok.com/test'
        assert args.method == '2'
        assert args.threads == 5
        assert args.service == '6'
        assert args.time == 60
        assert args.proxy == '1.2.3.4:8080'
        assert args.phpsessid == 'abc123'
        assert args.target == 50000
        assert args.max_cycles == 100
        assert args.json_log is True


# ============================================================
# input_with_timeout
# ============================================================

def test_input_with_timeout_returns_empty_on_timeout():
    import sys
    from zefoy_bot import input_with_timeout
    if platform.system() == 'Windows':
        with patch('msvcrt.kbhit', return_value=False):
            result = input_with_timeout('test: ', timeout_sec=0.1)
            assert result == ''
    else:
        with patch('select.select', return_value=([], [], [])):
            result = input_with_timeout('test: ', timeout_sec=0.1)
            assert result == ''


# ============================================================
# notify_desktop
# ============================================================

def test_notify_desktop_does_not_crash():
    from zefoy_bot import notify_desktop
    notify_desktop('Test', 'Test message')


# ============================================================
# validate_captcha_page — tightened fallback (#20)
# ============================================================

def test_validate_captcha_page_no_false_positive():
    html = '<html><body><p>This page mentions captcha in text but has no actual form</p></body></html>'
    assert validate_captcha_page(html) is False


def test_validate_captcha_page_strict():
    html = '<html><body><input type="search" name="xyz123"></body></html>'
    assert validate_captcha_page(html) is True
