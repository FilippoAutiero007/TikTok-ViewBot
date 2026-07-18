import pytest
from unittest.mock import patch, MagicMock

from main import (
    decode, http_request, validate_captcha_page,
    parse_captcha_fields, create_session, parse_timer,
    check_service_status, validate_tiktok_url, build_multipart,
    SERVICES,
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
    assert 'zefoy.com' in session.headers.get('authority', '')
    assert session.headers['x-requested-with'] == 'XMLHttpRequest'


# --- validate_captcha_page ---

def test_validate_valid_html():
    html = '<html>' + 'x' * 1500 + '<form>captcha</form>Enter the word shown in the image'
    assert validate_captcha_page(html) is True


def test_validate_empty_html(caplog):
    assert validate_captcha_page('') is False
    assert 'Empty response' in caplog.text


def test_validate_none_html(caplog):
    assert validate_captcha_page(None) is False


def test_validate_short_html(caplog):
    html = '<html>captcha</html>'
    assert validate_captcha_page(html) is False
    assert 'too short' in caplog.text


def test_validate_captcha_with_hidden_error_modal(caplog):
    html = 'x' * 1500 + 'captcha Enter the word shown in the image'
    assert validate_captcha_page(html) is True


def test_validate_no_captcha_keyword(caplog):
    html = '<html>' + 'x' * 1500 + '</html>'
    assert validate_captcha_page(html) is False
    assert 'No captcha detected' in caplog.text


def test_validate_no_captcha_form(caplog):
    html = 'captcha some text but no form ' + 'x' * 1500
    assert validate_captcha_page(html) is False
    assert 'Captcha form not found' in caplog.text


# --- parse_captcha_fields ---

def test_parse_finds_text_inputs():
    html = '<input type="text" name="captcha_field" value="test123">'
    inputs, hidden, img = parse_captcha_fields(html)
    assert len(inputs) > 0
    assert inputs[0][0] == 'captcha_field'


def test_parse_finds_hidden_fields():
    html = '<input type="hidden" name="token" value="abc123">'
    inputs, hidden, img = parse_captcha_fields(html)
    assert len(hidden) > 0
    assert hidden[0][0] == 'token'


def test_parse_finds_captcha_image():
    html = '<img src="/assets/captcha.png">'
    inputs, hidden, img = parse_captcha_fields(html)
    assert img is not None
    assert 'captcha.png' in img


def test_parse_full_captcha_page():
    html = '<form><input type="hidden" name="captcha_encoded" value="xyz"><input type="text" name="captchalogin" placeholder="Enter captcha"><img src="/assets/captcha.png"></form>'
    inputs, hidden, img = parse_captcha_fields(html)
    assert len(inputs) > 0
    assert len(hidden) > 0
    assert img is not None


def test_parse_no_fields():
    html = '<html><body>No form here</body></html>'
    inputs, hidden, img = parse_captcha_fields(html)
    assert inputs == []
    assert hidden == []
    assert img is None


def test_parse_fallback_image():
    html = '<img src="random_image.jpg">'
    inputs, hidden, img = parse_captcha_fields(html)
    assert img is not None


# --- http_request ---

@patch('main.sleep', return_value=None)
def test_http_request_success(mock_sleep):
    session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    session.request.return_value = mock_resp

    resp = http_request(session, 'GET', 'https://example.com')
    assert resp.status_code == 200


@patch('main.sleep', return_value=None)
def test_http_request_retries_on_429(mock_sleep):
    session = MagicMock()
    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_ok = MagicMock()
    resp_ok.status_code = 200
    session.request.side_effect = [resp_429, resp_ok]

    resp = http_request(session, 'GET', 'https://example.com', max_retries=3)
    assert resp.status_code == 200
    assert session.request.call_count == 2


@patch('main.sleep', return_value=None)
def test_http_request_retries_on_500(mock_sleep):
    session = MagicMock()
    resp_500 = MagicMock()
    resp_500.status_code = 500
    resp_ok = MagicMock()
    resp_ok.status_code = 200
    session.request.side_effect = [resp_500, resp_ok]

    resp = http_request(session, 'GET', 'https://example.com', max_retries=3)
    assert resp.status_code == 200
    assert session.request.call_count == 2


@patch('main.sleep', return_value=None)
def test_http_request_gives_up_after_max_retries_429(mock_sleep):
    session = MagicMock()
    resp_429 = MagicMock()
    resp_429.status_code = 429
    session.request.return_value = resp_429

    with pytest.raises(Exception, match='Failed after'):
        http_request(session, 'GET', 'https://example.com', max_retries=2)
    assert session.request.call_count == 3


@patch('main.sleep', return_value=None)
def test_http_request_timeout_retries(mock_sleep):
    from requests.exceptions import Timeout
    session = MagicMock()
    session.request.side_effect = [Timeout('timeout'), MagicMock(status_code=200)]

    resp = http_request(session, 'GET', 'https://example.com', max_retries=3)
    assert resp.status_code == 200
    assert session.request.call_count == 2


@patch('main.sleep', return_value=None)
def test_http_request_respects_timeout_param(mock_sleep):
    session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    session.request.return_value = mock_resp

    http_request(session, 'GET', 'https://example.com', timeout=5)
    _, kwargs = session.request.call_args
    assert kwargs['timeout'] == 5


@patch('main.sleep')
def test_http_request_exponential_backoff_429(mock_sleep):
    session = MagicMock()
    resp_429 = MagicMock()
    resp_429.status_code = 429
    session.request.return_value = resp_429

    with pytest.raises(Exception):
        http_request(session, 'GET', 'https://example.com', max_retries=2)

    delays = [call.args[0] for call in mock_sleep.call_args_list]
    assert delays == [1, 2, 4]


# --- parse_timer ---

def test_parse_timer_ltm():
    html = 'var ltm=120;'
    assert parse_timer(html) == 120


def test_parse_timer_ltm_zero():
    html = 'var ltm=0;'
    assert parse_timer(html) == 0


def test_parse_timer_please_wait_min_sec():
    html = 'Please wait 3 minutes 45 seconds'
    assert parse_timer(html) == 225


def test_parse_timer_please_wait_seconds():
    html = 'Please wait 90 seconds'
    assert parse_timer(html) == 90


def test_parse_timer_no_match():
    html = '<html>no timer here</html>'
    assert parse_timer(html) == 0


# --- check_service_status ---

def test_service_status_enabled():
    html = '<div class="t-views-button">Views</div>'
    assert check_service_status(html, 't-views-button') is True


def test_service_status_disabled():
    html = '<div class="t-views-button disabled">Views</div>'
    assert check_service_status(html, 't-views-button') is False


def test_service_status_not_found():
    html = '<div class="other-button">Other</div>'
    assert check_service_status(html, 't-views-button') is False


# --- build_multipart ---

def test_build_multipart_format():
    body, boundary = build_multipart('test_key', 'test_value')
    assert 'test_key' in body
    assert 'test_value' in body
    assert boundary.startswith('----WebKitFormBoundary')
    assert body.startswith(f'--{boundary}\r\n')
    assert body.endswith(f'--{boundary}--\r\n')


# --- SERVICES config ---

def test_services_count():
    assert len(SERVICES) == 7


def test_services_have_required_keys():
    for key, svc in SERVICES.items():
        assert 'name' in svc
        assert 'selector' in svc
