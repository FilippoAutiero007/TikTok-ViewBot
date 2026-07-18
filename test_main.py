import pytest
from unittest.mock import patch, MagicMock, Mock
from requests.exceptions import ConnectionError, Timeout

from main import (
    log, decode, http_request, validate_captcha_page,
    parse_captcha_fields, create_session,
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


# --- log ---

def test_log_outputs_info(capsys):
    log('test message')
    out = capsys.readouterr().out
    assert 'INFO' in out
    assert 'test message' in out


def test_log_outputs_error_level(capsys):
    log('error happened', 'ERROR')
    out = capsys.readouterr().out
    assert 'ERROR' in out
    assert 'error happened' in out


def test_log_outputs_warning_level(capsys):
    log('warning msg', 'WARNING')
    out = capsys.readouterr().out
    assert 'WARNING' in out


def test_log_outputs_debug_level(capsys):
    log('debug msg', 'DEBUG')
    out = capsys.readouterr().out
    assert 'DEBUG' in out


# --- create_session ---

def test_create_session_has_headers():
    session = create_session()
    assert 'user-agent' in session.headers
    assert 'zefoy.com' in session.headers.get('authority', '')
    assert session.headers['x-requested-with'] == 'XMLHttpRequest'


# --- validate_captcha_page ---

def test_validate_valid_html():
    html = '<html>' + 'x' * 1500 + '<form>captcha</form>'
    assert validate_captcha_page(html) is True


def test_validate_empty_html(capsys):
    assert validate_captcha_page('') is False
    assert 'Empty response' in capsys.readouterr().out


def test_validate_none_html(capsys):
    assert validate_captcha_page(None) is False


def test_validate_short_html(capsys):
    html = '<html>captcha</html>'
    assert validate_captcha_page(html) is False
    assert 'too short' in capsys.readouterr().out


def test_validate_incorrect_captcha(capsys):
    html = 'x' * 1500 + 'Captcha code is incorrect'
    assert validate_captcha_page(html) is False
    assert 'Captcha incorrect' in capsys.readouterr().out


def test_validate_no_captcha_keyword(capsys):
    html = '<html>' + 'x' * 1500 + '</html>'
    assert validate_captcha_page(html) is False
    assert 'No captcha detected' in capsys.readouterr().out


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
    session.request.assert_called_once()


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
def test_http_request_gives_up_after_max_retries_5xx(mock_sleep):
    session = MagicMock()
    resp_503 = MagicMock()
    resp_503.status_code = 503
    session.request.return_value = resp_503

    with pytest.raises(Exception, match='Failed after'):
        http_request(session, 'GET', 'https://example.com', max_retries=2)
    assert session.request.call_count == 3


@patch('main.sleep', return_value=None)
def test_http_request_timeout_retries(mock_sleep):
    session = MagicMock()
    session.request.side_effect = [Timeout('timeout'), MagicMock(status_code=200)]

    resp = http_request(session, 'GET', 'https://example.com', max_retries=3)
    assert resp.status_code == 200
    assert session.request.call_count == 2


@patch('main.sleep', return_value=None)
def test_http_request_connection_error_gives_up(mock_sleep):
    session = MagicMock()
    session.request.side_effect = ConnectionError('refused')

    with pytest.raises(ConnectionError):
        http_request(session, 'GET', 'https://example.com', max_retries=1)
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


# --- exponential backoff delays ---

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


@patch('main.sleep')
def test_http_request_exponential_backoff_5xx(mock_sleep):
    session = MagicMock()
    resp_500 = MagicMock()
    resp_500.status_code = 500
    session.request.return_value = resp_500

    with pytest.raises(Exception):
        http_request(session, 'GET', 'https://example.com', max_retries=2)

    delays = [call.args[0] for call in mock_sleep.call_args_list]
    assert delays == [1, 2, 4]
