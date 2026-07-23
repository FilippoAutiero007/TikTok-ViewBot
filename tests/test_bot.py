import os
import pytest
from unittest.mock import patch, MagicMock

from zefoy_bot import (
    decode, http_request, validate_tiktok_url, validate_captcha_page,
    parse_captcha_fields, create_session, parse_timer,
    check_service_status, build_multipart, extract_key_from_html,
    SERVICES, DEBUG_DIR,
)


# --- decode ---

def test_decode_valid():
    import base64
    from urllib.parse import quote
    original = b'hello world'
    encoded = quote(base64.b64encode(original).decode())[::-1]
    assert decode(encoded) == 'hello world'


def test_decode_empty_string():
    import base64
    from urllib.parse import quote
    encoded = quote(base64.b64encode(b'')[::-1].decode())
    assert decode(encoded) == ''


# --- extract_key_from_html ---

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


# --- validate_tiktok_url ---

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


# --- create_session ---

def test_create_session_has_headers():
    session = create_session()
    assert 'user-agent' in session.headers


def test_create_session_is_requests_session():
    import requests
    session = create_session()
    assert isinstance(session, requests.Session)


# --- validate_captcha_page ---

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


# --- parse_captcha_fields ---

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


# --- http_request ---

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


# --- parse_timer ---

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


# --- check_service_status ---

def test_service_enabled():
    html = '<div class="t-views-button">Views</div>'
    assert check_service_status(html, 't-views-button') is True


def test_service_disabled():
    html = '<div class="t-views-button disabled">Views</div>'
    assert check_service_status(html, 't-views-button') is False


def test_service_not_found():
    html = '<div class="other">X</div>'
    assert check_service_status(html, 't-views-button') is False


# --- build_multipart ---

def test_build_multipart():
    body, boundary = build_multipart('key', 'value')
    assert 'key' in body
    assert 'value' in body
    assert boundary.startswith('----WebKitFormBoundary')


def test_build_multipart_unique():
    _, b1 = build_multipart('k', 'v')
    _, b2 = build_multipart('k', 'v')
    assert b1 != b2


# --- SERVICES ---

def test_services_count():
    assert len(SERVICES) == 8


def test_services_keys():
    for key, svc in SERVICES.items():
        assert 'name' in svc
        assert 'selector' in svc
