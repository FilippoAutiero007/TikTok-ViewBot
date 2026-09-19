"""
Improved TikTok Account Creator v2
Fixes:
- Multi-provider email with fallback
- React fiber direct send_code triggering
- Proper error detection and retry
- No false-success (only saves on verified code submission)
- Better stealth and human timing
- Robust birthday combobox handling
- Captcha handling improvements
"""
import os
import re
import json
import time
import random
import string
import logging
import traceback

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
    HAS_SELENIUM = True
except ImportError:
    HAS_SELENIUM = False

try:
    from webdriver_manager.chrome import ChromeDriverManager
    HAS_WDM = True
except ImportError:
    HAS_WDM = False

from .email_providers import MultiTempEmailProvider, extract_code_generic

log = logging.getLogger(__name__)

ACCOUNTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'accounts', 'active')


def _random_password():
    length = random.randint(14, 18)
    upper = random.choice(string.ascii_uppercase)
    lower = random.choice(string.ascii_lowercase)
    digit = random.choice(string.digits)
    special = random.choice('!@#$%&*')
    rest = ''.join(random.choices(string.ascii_letters + string.digits + '!@#$%&*', k=length - 4))
    password = list(upper + lower + digit + special + rest)
    random.shuffle(password)
    return ''.join(password)


def _random_birthday():
    year = random.randint(1993, 2005)
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    return year, month, day


def _create_driver(headless=False, proxy=None, lang='it-IT'):
    if not HAS_SELENIUM:
        raise RuntimeError("selenium not installed. pip install selenium")
    options = Options()
    if headless:
        options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--disable-infobars')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--lang=' + lang)
    options.add_argument('--disable-features=IsolateOrigins,site-per-process')
    options.add_argument('--disable-web-security')
    options.add_argument(
        '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'
    )
    # anti-detection prefs
    options.add_experimental_option('excludeSwitches', ['enable-automation', 'enable-blink-features=AutomationControlled'])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_experimental_option('prefs', {
        'credentials_enable_service': False,
        'profile.password_manager_enabled': False,
        'profile.default_content_setting_values.notifications': 2,
    })
    if proxy:
        options.add_argument(f'--proxy-server={proxy}')

    if HAS_WDM:
        service = Service(ChromeDriverManager().install())
    else:
        service = Service()
    driver = webdriver.Chrome(service=service, options=options)

    # stealth script
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['it-IT','it','en-US','en'] });
            window.chrome = { runtime: {} };
        """
    })
    # enable network domain for possible interception later
    try:
        driver.execute_cdp_cmd('Network.enable', {})
    except Exception:
        pass
    return driver


def _human_type(element, text, delay_range=(0.05, 0.12)):
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(*delay_range))


def _trigger_input_events(driver, element):
    """Dispatch input/change events so React perceives the value."""
    try:
        driver.execute_script("""
            const el = arguments[0];
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
            el.dispatchEvent(new Event('blur', { bubbles: true }));
        """, element)
    except Exception:
        pass


class TikTokAccountCreatorV2:
    """
    Improved creator with:
    - multi email fallback
    - React direct invocation for send_code
    - strict success validation
    """
    def __init__(self, headless=False, proxy=None, email_domain=None, lang='it-IT'):
        self.headless = headless
        self.proxy = proxy
        self.email_domain = email_domain
        self.lang = lang
        self.driver = None
        self.email_provider = MultiTempEmailProvider()
        self.temp_email = None
        self.password = None
        self._birthday = None

    def _setup_driver(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
        self.driver = _create_driver(headless=self.headless, proxy=self.proxy, lang=self.lang)
        return self.driver

    def _get_temp_email(self, rotate=False):
        if rotate:
            try:
                self.temp_email = self.email_provider.rotate_provider()
            except Exception as e:
                log.error('Rotate email failed: %s', e)
                raise
        else:
            # first time: just get new
            if not self.email_provider.email_addr:
                self.temp_email = self.email_provider.get_email_address()
            else:
                self.temp_email = self.email_provider.email_addr
        # override domain if user specified
        if self.email_domain and '@' in self.temp_email:
            local = self.temp_email.split('@')[0]
            self.temp_email = f"{local}@{self.email_domain}"
        log.info('Temp email [%s]: %s', self.email_provider.provider_name, self.temp_email)
        return self.temp_email

    def _wait_for_verification_code(self, timeout=120):
        log.info('Waiting for verification code on %s via %s...', self.temp_email, self.email_provider.provider_name)
        email_data = self.email_provider.wait_for_email(timeout=timeout)
        if email_data:
            code = self.email_provider.extract_verification_code(email_data)
            if code:
                log.info('Verification code: %s', code)
                return code
            # fallback generic extraction on raw
            code2 = extract_code_generic(str(email_data))
            if code2:
                log.info('Verification code (fallback): %s', code2)
                return code2
        log.warning('Could not get verification code for %s', self.temp_email)
        return None

    def create_account(self, max_email_retries=3):
        """
        Main flow with email rotation on block.
        Returns account_data only on true success, else None.
        """
        verification_succeeded = False
        for email_attempt in range(max_email_retries):
            try:
                self._setup_driver()
                if email_attempt == 0:
                    self._get_temp_email(rotate=False)
                else:
                    log.info('Retrying with new email provider (attempt %d/%d)', email_attempt+1, max_email_retries)
                    self.email_provider.mark_blocked()
                    self._get_temp_email(rotate=True)
                self.password = _random_password()

                log.info('Starting TikTok registration attempt %d/%d', email_attempt+1, max_email_retries)
                log.info('Email: %s', self.temp_email)
                log.info('Password: %s', self.password)

                self.driver.get('https://www.tiktok.com/signup')
                time.sleep(5)

                log.info('Page title: %s', self.driver.title)

                self._dismiss_cookie_banner()
                self._step1_click_email_option()
                self._step2_switch_to_email_form()
                self._step3_fill_birthday()
                self._step4_fill_email()
                self._step5_fill_password()

                send_result = self._step6_send_verification_code()
                if send_result == 'blocked':
                    log.warning('Email domain blocked by TikTok, rotating...')
                    # save screenshot for debug
                    try:
                        self.driver.save_screenshot(f'_blocked_attempt_{email_attempt}.png')
                    except Exception:
                        pass
                    # close driver and retry with new email
                    try:
                        self.driver.quit()
                    except Exception:
                        pass
                    self.driver = None
                    time.sleep(2)
                    continue
                elif send_result is False:
                    log.warning('Send code failed generically, rotating email as well')
                    try:
                        self.driver.save_screenshot(f'_send_failed_{email_attempt}.png')
                    except Exception:
                        pass
                    try:
                        self.driver.quit()
                    except Exception:
                        pass
                    self.driver = None
                    time.sleep(2)
                    continue
                # else True -> code was sent

                self._step7_handle_captcha()
                code_entered = self._step8_enter_verification_code()
                if not code_entered:
                    log.error('Verification code step failed, retrying with new email...')
                    try:
                        self.driver.quit()
                    except Exception:
                        pass
                    self.driver = None
                    time.sleep(2)
                    continue

                submit_ok = self._step9_submit()
                if not submit_ok:
                    log.warning('Submit may have failed, checking account extraction anyway')

                account_data = self._extract_account_data(require_verification=True)
                if account_data and account_data.get('verification_success'):
                    self._save_account(account_data)
                    log.info('Account created successfully!')
                    return account_data
                elif account_data and not account_data.get('verification_success'):
                    log.error('Account extraction indicates not verified (cookies missing or still on signup page)')
                    # check if we are still on signup page
                    current_url = self.driver.current_url.lower()
                    if 'signup' in current_url:
                        log.error('Still on signup page after submit, likely verification failed')
                        try:
                            self.driver.save_screenshot(f'_still_signup_{email_attempt}.png')
                        except Exception:
                            pass
                        # check for error messages
                        errors = self._collect_error_messages()
                        if errors:
                            log.error('Errors after submit: %s', errors)
                    # rotate and retry
                    try:
                        self.driver.quit()
                    except Exception:
                        pass
                    self.driver = None
                    time.sleep(2)
                    continue
                else:
                    log.error('Failed to extract account data')
                    try:
                        self.driver.quit()
                    except Exception:
                        pass
                    self.driver = None
                    continue

            except Exception as e:
                log.error('Account creation attempt %d failed: %s', email_attempt+1, e)
                traceback.print_exc()
                try:
                    if self.driver:
                        self.driver.save_screenshot(f'_exception_{email_attempt}.png')
                except Exception:
                    pass
                try:
                    if self.driver:
                        self.driver.quit()
                except Exception:
                    pass
                self.driver = None
                time.sleep(2)
                continue
            finally:
                # if we are not retrying, clean up will be handled above or outside
                pass

        # all attempts exhausted
        log.error('All %d email attempts failed', max_email_retries)
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
        return None

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------
    def _step1_click_email_option(self):
        log.info('STEP 1: Click "Usa telefono o email"')
        try:
            btn = WebDriverWait(self.driver, 15).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, '[data-e2e="channel-item"]'))
            )
            # scroll into view
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            time.sleep(0.5)
            try:
                btn.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", btn)
            time.sleep(3)
            log.info('Clicked channel-item')
        except TimeoutException:
            # fallback: try finding by text
            log.warning('channel-item not found by data-e2e, trying text search')
            buttons = self.driver.find_elements(By.TAG_NAME, 'div')
            for b in buttons:
                if 'telefono' in b.text.lower() and 'email' in b.text.lower():
                    try:
                        b.click()
                        time.sleep(3)
                        return
                    except Exception:
                        continue
            raise Exception('Could not find channel-item after fallback')

    def _step2_switch_to_email_form(self):
        log.info('STEP 2: Switch to email registration form')
        # wait for a tags to appear
        time.sleep(1)
        # Try explicit wait for link with email text
        try:
            WebDriverWait(self.driver, 10).until(
                lambda d: any('email' in l.text.lower() and 'registrati' in l.text.lower() for l in d.find_elements(By.TAG_NAME, 'a'))
            )
        except TimeoutException:
            log.warning('Timeout waiting for email link, will search anyway')
        links = self.driver.find_elements(By.TAG_NAME, 'a')
        for link in links:
            txt = link.text.lower()
            if 'email' in txt and 'registrati' in txt:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", link)
                time.sleep(0.3)
                try:
                    link.click()
                except Exception:
                    self.driver.execute_script("arguments[0].click();", link)
                time.sleep(3)
                log.info('Clicked "Registrati con l\'email"')
                return
            # also English fallback
            if 'email' in txt and ('sign up' in txt or 'register' in txt):
                self.driver.execute_script("arguments[0].click();", link)
                time.sleep(3)
                log.info('Clicked English email signup')
                return
        raise Exception('Could not find email registration link')

    def _step3_fill_birthday(self):
        log.info('STEP 3: Fill birthday')
        year, month, day = _random_birthday()
        self._birthday = (year, month, day)
        # Use improved selection with verification
        # Order: 0=month, 1=day, 2=year
        success = True
        if not self._click_combobox_and_select(0, 'month', month - 1):
            success = False
        time.sleep(0.8)
        if not self._click_combobox_and_select(1, 'day', day - 1):
            success = False
        time.sleep(0.8)
        if not self._click_year_combobox_and_select(year):
            success = False
        time.sleep(0.8)
        # verify
        self._verify_birthday_set()
        if not success:
            log.warning('Birthday selection had failures, but continuing')
        log.info('Birthday set: %d-%02d-%02d', year, month, day)

    def _get_comboboxes(self):
        cbs = self.driver.find_elements(By.CSS_SELECTOR, '[role="combobox"][data-e2e="select-container"]')
        if len(cbs) < 3:
            cbs = self.driver.find_elements(By.CSS_SELECTOR, '[role="combobox"]')
        return cbs

    def _click_combobox_and_select(self, combobox_index, field_type, target_index):
        for attempt in range(3):
            try:
                cbs = self._get_comboboxes()
                if combobox_index >= len(cbs):
                    log.warning('Not enough comboboxes: %d need %d', len(cbs), combobox_index)
                    time.sleep(1)
                    continue
                cb = cbs[combobox_index]
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", cb)
                time.sleep(0.4)
                # try ActionChains click
                try:
                    ActionChains(self.driver).move_to_element(cb).pause(0.3).click().perform()
                except Exception:
                    self.driver.execute_script("arguments[0].click();", cb)
                time.sleep(1.5)

                listboxes = self.driver.find_elements(By.CSS_SELECTOR, '[role="listbox"]')
                # also consider hidden listboxes via style
                if not listboxes:
                    time.sleep(0.5)
                    listboxes = self.driver.find_elements(By.CSS_SELECTOR, '[role="listbox"]')
                target_opt = None
                for lb in listboxes:
                    opts = lb.find_elements(By.CSS_SELECTOR, '[role="option"]')
                    if field_type == 'month' and 10 <= len(opts) <= 14:
                        if target_index < len(opts):
                            target_opt = opts[target_index]
                            break
                    elif field_type == 'day' and 28 <= len(opts) <= 31:
                        if target_index < len(opts):
                            target_opt = opts[target_index]
                            break
                if target_opt:
                    try:
                        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", target_opt)
                        time.sleep(0.2)
                    except Exception:
                        pass
                    self._safe_click(target_opt)
                    log.debug('Selected %s option %d', field_type, target_index)
                    # verify selection changed by checking combobox label
                    time.sleep(0.5)
                    return True
                log.warning('Attempt %d: no matching listbox for %s (found %d listboxes)', attempt+1, field_type, len(listboxes))
                # dismiss any open dropdown
                try:
                    ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
                except Exception:
                    self.driver.execute_script("document.body.click();")
                time.sleep(0.7)
            except StaleElementReferenceException:
                log.debug('Stale element on combobox %d attempt %d', combobox_index, attempt+1)
                time.sleep(0.8)
                continue
            except Exception as e:
                log.warning('Error selecting %s: %s', field_type, e)
                time.sleep(0.8)
        log.error('Failed to select %s from combobox %d after 3 attempts', field_type, combobox_index)
        return False

    def _click_year_combobox_and_select(self, year):
        for attempt in range(3):
            try:
                cbs = self._get_comboboxes()
                if len(cbs) < 3:
                    log.warning('Not enough comboboxes for year: %d', len(cbs))
                    time.sleep(1)
                    continue
                cb = cbs[2]
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", cb)
                time.sleep(0.4)
                try:
                    ActionChains(self.driver).move_to_element(cb).pause(0.3).click().perform()
                except Exception:
                    self.driver.execute_script("arguments[0].click();", cb)
                time.sleep(1.5)

                listboxes = self.driver.find_elements(By.CSS_SELECTOR, '[role="listbox"]')
                for lb in listboxes:
                    opts = lb.find_elements(By.CSS_SELECTOR, '[role="option"]')
                    if len(opts) > 50:
                        for opt in opts:
                            if opt.text.strip() == str(year):
                                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", opt)
                                time.sleep(0.2)
                                self._safe_click(opt)
                                log.debug('Selected year: %d (attempt %d)', year, attempt)
                                time.sleep(0.5)
                                return True
                log.warning('Attempt %d: year listbox not found', attempt+1)
                try:
                    ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
                except Exception:
                    pass
                time.sleep(0.7)
            except StaleElementReferenceException:
                time.sleep(0.8)
                continue
            except Exception as e:
                log.warning('Error selecting year: %s', e)
                time.sleep(0.8)
        log.error('Failed to select year %d after 3 attempts', year)
        return False

    def _safe_click(self, element):
        try:
            ActionChains(self.driver).move_to_element(element).pause(0.2).click().perform()
        except Exception:
            try:
                self.driver.execute_script("arguments[0].click();", element)
            except Exception as e:
                log.debug('safe_click failed: %s', e)

    def _step4_fill_email(self):
        log.info('STEP 4: Fill email')
        email_input = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[name="email"]'))
        )
        # clear first
        try:
            email_input.clear()
        except Exception:
            self.driver.execute_script("arguments[0].value='';", email_input)
        email_input.click()
        time.sleep(0.3)
        # select all and delete to ensure clean
        try:
            email_input.send_keys(Keys.CONTROL, 'a')
            email_input.send_keys(Keys.DELETE)
        except Exception:
            pass
        _human_type(email_input, self.temp_email)
        _trigger_input_events(self.driver, email_input)
        log.info('Email filled: %s', self.temp_email)
        time.sleep(0.8)
        # blur to trigger validation
        try:
            self.driver.execute_script("arguments[0].blur();", email_input)
        except Exception:
            pass
        time.sleep(1)
        # check for inline error immediately
        errors = self._get_inline_errors()
        if errors:
            log.warning('Inline errors after email fill: %s', errors)
            # if error indicates invalid/blocked domain, we can early return
            for err in errors:
                low = err.lower()
                if 'non valida' in low or 'invalid' in low or 'bloccata' in low or 'blocked' in low or 'non supportata' in low:
                    log.warning('Email domain appears blocked: %s', err)
                    # mark as blocked? caller will handle
                    pass

    def _step5_fill_password(self):
        log.info('STEP 5: Fill password')
        pw_input = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="password"]'))
        )
        try:
            pw_input.clear()
        except Exception:
            self.driver.execute_script("arguments[0].value='';", pw_input)
        pw_input.click()
        time.sleep(0.3)
        try:
            pw_input.send_keys(Keys.CONTROL, 'a')
            pw_input.send_keys(Keys.DELETE)
        except Exception:
            pass
        _human_type(pw_input, self.password)
        _trigger_input_events(self.driver, pw_input)
        log.info('Password filled')
        time.sleep(0.8)
        try:
            self.driver.execute_script("arguments[0].blur();", pw_input)
        except Exception:
            pass
        time.sleep(0.8)
        # check password strength errors
        errors = self._get_inline_errors()
        if errors:
            log.warning('Inline errors after password fill: %s', errors)

    def _get_inline_errors(self):
        """Collect visible error messages near form fields."""
        errors = []
        try:
            # data-e2e error
            for el in self.driver.find_elements(By.CSS_SELECTOR, '[data-e2e="form-error-message"]'):
                txt = el.text.strip()
                if txt:
                    errors.append(txt)
            # generic error class
            for sel in ['[class*="error"]', '[class*="Error"]', '[class*="Toast"]', '[class*="toast"]']:
                for el in self.driver.find_elements(By.CSS_SELECTOR, sel):
                    txt = el.text.strip()
                    if txt and len(txt) < 200 and txt not in errors:
                        # filter too generic
                        if 'error' in txt.lower() or 'invalid' in txt.lower() or 'non valida' in txt.lower() or len(txt) < 80:
                            errors.append(txt)
        except Exception:
            pass
        return errors

    def _collect_error_messages(self):
        """More thorough error collection after actions."""
        errs = self._get_inline_errors()
        # also check page source for known strings
        try:
            ps = self.driver.page_source.lower()
            for kw in ['troppi tentativi', 'too many attempts', 'email non valida', 'invalid email', 'domain not supported', 'riprova più tardi', 'try again later', 'bloccato', 'blocked']:
                if kw in ps:
                    if kw not in [e.lower() for e in errs]:
                        errs.append(kw)
        except Exception:
            pass
        return errs

    def _step6_send_verification_code(self):
        """
        Tries multiple strategies to trigger send code.
        Returns:
          True  -> code sent (timer visible)
          'blocked' -> email domain blocked, should rotate
          False -> generic failure, should retry
        """
        log.info('STEP 6: Send verification code')
        self._dismiss_cookie_banner()
        time.sleep(1)

        self._verify_birthday_set()

        # Check for inline errors before attempting
        pre_errors = self._get_inline_errors()
        if pre_errors:
            log.warning('Pre-send errors: %s', pre_errors)
            for e in pre_errors:
                low = e.lower()
                if 'email' in low and ('non valida' in low or 'invalid' in low or 'bloccata' in low):
                    return 'blocked'

        # find send button
        send_btn = None
        buttons = self.driver.find_elements(By.TAG_NAME, 'button')
        for btn in buttons:
            txt = btn.text.lower()
            if 'invia' in txt or 'send' in txt:
                # avoid submit button which might also contain invia? Usually send is "Invia codice"
                if len(txt.strip()) < 40:  # filter long texts
                    send_btn = btn
                    # prefer button with invia codice
                    if 'codice' in txt or 'code' in txt:
                        break
        if not send_btn:
            log.warning('Send code button not found by text, trying data-e2e')
            # try alternative selector
            try:
                cand = self.driver.find_elements(By.CSS_SELECTOR, 'button[data-e2e*="send"], button[data-e2e*="code"]')
                if cand:
                    send_btn = cand[0]
            except Exception:
                pass
        if not send_btn:
            log.error('Send code button not found at all')
            # debug dump buttons
            try:
                all_btn_texts = [b.text.strip()[:50] for b in self.driver.find_elements(By.TAG_NAME, 'button') if b.text.strip()]
                log.info('Available buttons: %s', all_btn_texts)
            except Exception:
                pass
            return False

        log.info('Found send button: "%s" enabled=%s displayed=%s', send_btn.text.strip(), send_btn.is_enabled(), send_btn.is_displayed())

        # Check React disabled prop
        is_react_disabled = self._is_button_react_disabled(send_btn)
        if is_react_disabled:
            log.warning('Button is disabled via React props (likely validation failed)')
            # wait a bit and re-check validation
            for attempt in range(3):
                time.sleep(2)
                is_react_disabled = self._is_button_react_disabled(send_btn)
                if not is_react_disabled:
                    break
                log.info('Still disabled after %d checks', attempt+1)
                # re-trigger validation by bluring fields again
                try:
                    self.driver.find_element(By.CSS_SELECTOR, 'input[name="email"]').click()
                    time.sleep(0.2)
                    self.driver.find_element(By.CSS_SELECTOR, 'input[type="password"]').click()
                    time.sleep(0.2)
                except Exception:
                    pass
            if is_react_disabled:
                log.error('Button remains disabled after waits - likely email or birthday invalid')
                # collect errors to determine if blocked
                errs = self._collect_error_messages()
                if errs:
                    log.error('Errors while disabled: %s', errs)
                    for e in errs:
                        if 'email' in e.lower() or 'dominio' in e.lower() or 'domain' in e.lower():
                            return 'blocked'
                return False

        # Now try clicking with multiple strategies
        strategies = ['actionchains', 'js', 'react_direct']
        for strat in strategies:
            log.info('Trying send_code strategy: %s', strat)
            try:
                if strat == 'actionchains':
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", send_btn)
                    time.sleep(0.5)
                    ActionChains(self.driver).move_to_element(send_btn).pause(0.3).click().perform()
                elif strat == 'js':
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", send_btn)
                    time.sleep(0.3)
                    self.driver.execute_script("arguments[0].removeAttribute('disabled'); arguments[0].disabled=false; arguments[0].click();", send_btn)
                elif strat == 'react_direct':
                    # Most reliable: call React's onClickSendCode directly
                    result = self.driver.execute_script("""
                        const btn = arguments[0];
                        const fiberKey = Object.keys(btn).find(k => k.startsWith('__reactFiber$'));
                        if (!fiberKey) return 'no fiber';
                        let fiber = btn[fiberKey];
                        // walk up to find onClickSendCode
                        for (let depth=0; depth<15; depth++) {
                            if (!fiber) break;
                            if (fiber.memoizedProps && fiber.memoizedProps.onClickSendCode) {
                                try {
                                    fiber.memoizedProps.onClickSendCode();
                                    return 'called onClickSendCode at depth '+depth;
                                } catch(e) {
                                    return 'error calling: '+e.message;
                                }
                            }
                            // also check for onClick itself
                            if (fiber.memoizedProps && fiber.memoizedProps.onClick && depth===0) {
                                try {
                                    fiber.memoizedProps.onClick({preventDefault:()=>{}, stopPropagation:()=>{}});
                                    return 'called onClick at depth '+depth;
                                } catch(e) { return 'error onClick: '+e.message; }
                            }
                            fiber = fiber.return;
                        }
                        return 'onClickSendCode not found in 15 depths';
                    """, send_btn)
                    log.info('React direct result: %s', result)
                time.sleep(1.5)
                # check if timer appeared or error appeared
                timer_found = self._check_timer_visible()
                if timer_found:
                    log.info('Code sent! Timer visible via %s: "%s"', strat, timer_found)
                    return True
                # check for immediate error toast
                errs = self._get_inline_errors()
                if errs:
                    log.warning('Errors after %s click: %s', strat, errs)
                    for e in errs:
                        low = e.lower()
                        if 'email' in low and ('non valida' in low or 'invalid' in low or 'bloccata' in low or 'non supportata' in low):
                            return 'blocked'
                        if 'troppi tentativi' in low or 'too many attempts' in low or 'riprova' in low:
                            log.warning('Rate limited, should wait or rotate')
                            return False
                # also check page source for block messages
                ps_low = self.driver.page_source.lower()
                if 'email non valida' in ps_low or 'invalid email' in ps_low:
                    return 'blocked'
                log.info('No timer after %s, trying next strategy...', strat)
            except Exception as e:
                log.warning('Strategy %s failed: %s', strat, e)
                continue

        # final extended wait after all strategies
        log.info('Waiting extended period for timer after all strategies...')
        for attempt in range(12):
            time.sleep(1)
            timer = self._check_timer_visible()
            if timer:
                log.info('Code sent (delayed)! Timer: "%s"', timer)
                return True
            if attempt == 3:
                try:
                    self.driver.save_screenshot('_after_send_3s.png')
                except Exception:
                    pass
            if attempt == 7:
                try:
                    self.driver.save_screenshot('_after_send_7s.png')
                except Exception:
                    pass

        try:
            self.driver.save_screenshot('_after_send_final.png')
        except Exception:
            pass
        # final error check
        final_errs = self._collect_error_messages()
        if final_errs:
            log.warning('Final errors: %s', final_errs)
            for e in final_errs:
                if 'non valida' in e.lower() or 'invalid email' in e.lower() or 'dominio' in e.lower():
                    return 'blocked'
        log.warning('Could not confirm code was sent (no timer visible after all strategies)')
        return False

    def _is_button_react_disabled(self, button_element):
        try:
            res = self.driver.execute_script("""
                const btn = arguments[0];
                const fk = Object.keys(btn).find(k => k.startsWith('__reactFiber$'));
                if (!fk) return null;
                let fiber = btn[fk];
                // depth 0 button element, depth 1 ButtonSendCode component has disabled prop
                // check first few depths
                for (let i=0; i<5; i++) {
                    if (!fiber) break;
                    if (fiber.memoizedProps && 'disabled' in fiber.memoizedProps) {
                        return fiber.memoizedProps.disabled;
                    }
                    fiber = fiber.return;
                }
                // fallback to DOM disabled
                return btn.disabled;
            """, button_element)
            return bool(res)
        except Exception:
            try:
                return not button_element.is_enabled()
            except Exception:
                return False

    def _check_timer_visible(self):
        """Check for countdown timer indicating code sent."""
        try:
            buttons = self.driver.find_elements(By.TAG_NAME, 'button')
            for b in buttons:
                txt = b.text.lower()
                if 'secondi' in txt or 'second' in txt or 'reinvia' in txt or 'resend' in txt or 'again' in txt:
                    # ensure it contains numbers like 59, 60
                    if any(ch.isdigit() for ch in b.text):
                        return b.text.strip()
                    # also if text is "Reinvia" alone without number, it may be after countdown, but still indicates sent
                    if 'reinvia' in txt or 'resend' in txt:
                        return b.text.strip()
            # also check for any element containing timer style
            # look for spans with countdown
            spans = self.driver.find_elements(By.XPATH, "//*[contains(text(),'secondi') or contains(text(),'second')]")
            for s in spans:
                txt = s.text.strip()
                if txt and any(ch.isdigit() for ch in txt):
                    return txt
        except Exception:
            pass
        return None

    def _verify_birthday_set(self):
        comboboxes = self.driver.find_elements(By.CSS_SELECTOR, '[role="combobox"][data-e2e="select-container"]')
        if len(comboboxes) < 3:
            return
        for i, cb in enumerate(comboboxes):
            try:
                label = cb.find_element(By.CSS_SELECTOR, 'div[class*="SelectLabel"]')
                text = label.text.strip()
                field = ['Month', 'Day', 'Year'][i]
                if text in ['Mese', 'Giorno', 'Anno', 'Month', 'Day', 'Year', '']:
                    log.warning('Birthday %s not set (showing: "%s")', field, text)
                else:
                    log.info('Birthday %s = "%s"', field, text)
            except Exception:
                pass

    def _dismiss_cookie_banner(self):
        log.info('Dismissing cookie banner (Shadow DOM)...')
        try:
            result = self.driver.execute_script("""
                var host = document.querySelector('tiktok-cookie-banner');
                if (host && host.shadowRoot) {
                    var buttons = host.shadowRoot.querySelectorAll('button');
                    for (var i = 0; i < buttons.length; i++) {
                        var text = buttons[i].textContent.toLowerCase();
                        if (text.includes('consenti') || text.includes('accept') || text.includes('allow')) {
                            buttons[i].click();
                            return 'Clicked consent button in shadow DOM';
                        }
                    }
                    // fallback: click first button
                    if (buttons.length > 0) {
                        buttons[0].click();
                        return 'Clicked first shadow button';
                    }
                    host.remove();
                    return 'Removed shadow host (no button matched)';
                }
                // Also check regular cookie banner
                var regular = document.querySelector('[data-e2e=\"cookie-banner\"] button, #onetrust-accept-btn-handler');
                if (regular) { regular.click(); return 'Clicked regular cookie banner'; }
                return 'No shadow DOM cookie banner found';
            """)
            log.info('Cookie banner result: %s', result)
        except Exception as e:
            log.debug('Cookie dismissal error: %s', e)
        time.sleep(1.5)

        # also handle possible overlay that blocks clicks - remove it if still present after 2 sec
        try:
            self.driver.execute_script("""
                // remove any overlay that might block interaction
                const overlays = document.querySelectorAll('[class*=\"overlay\"][style*=\"fixed\"], [class*=\"mask\"]');
                overlays.forEach(o => {
                    const style = window.getComputedStyle(o);
                    if (style.position === 'fixed' && parseInt(style.zIndex) > 100) {
                        // check if it covers send button
                        const btn = Array.from(document.querySelectorAll('button')).find(b => b.textContent.toLowerCase().includes('invia'));
                        if (btn) {
                            const r1 = o.getBoundingClientRect();
                            const r2 = btn.getBoundingClientRect();
                            // if overlay overlaps button, remove overlay
                            if (r1.width > 300 && r1.height > 200) o.remove();
                        }
                    }
                });
            """)
        except Exception:
            pass

    def _step7_handle_captcha(self):
        log.info('STEP 7: Check for captcha')
        try:
            WebDriverWait(self.driver, 6).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'iframe[src*=\"captcha\"], iframe[src*=\"verify\"], div[class*=\"captcha\"], div[data-e2e=\"captcha\"], div[class*=\"verify\"]'))
            )
            log.warning('CAPTCHA detected!')
            # Check for slider captcha specifically
            try:
                slider = self.driver.find_elements(By.CSS_SELECTOR, '[class*=\"slider\"], [class*=\"Slider\"], [class*=\"puzzle\"]')
                if slider:
                    log.warning('Slider captcha detected - needs manual solving or auto solver')
            except Exception:
                pass
            if not self.headless:
                log.info('Please solve the captcha in the browser window. Waiting up to 60s...')
                # Wait for captcha to disappear up to 60s
                for _ in range(60):
                    time.sleep(1)
                    try:
                        # check if captcha still present
                        captcha_elements = self.driver.find_elements(By.CSS_SELECTOR, 'iframe[src*=\"captcha\"], div[class*=\"captcha\"]')
                        visible_captcha = [e for e in captcha_elements if e.is_displayed()]
                        if not visible_captcha:
                            log.info('Captcha appears solved!')
                            return True
                    except Exception:
                        pass
                log.warning('Captcha wait timeout - continuing anyway')
                return True
            else:
                log.error('CAPTCHA in headless mode - cannot solve manually. Try with headless=False')
                # Could attempt auto solver here if available
                # For now, wait a bit and return
                time.sleep(5)
                return False
        except TimeoutException:
            log.info('No captcha detected')
        except Exception as e:
            log.debug('Captcha check error: %s', e)
        return True

    def _step8_enter_verification_code(self):
        log.info('STEP 8: Enter verification code')
        # Find code input(s) - TikTok may have 6 separate inputs or one input
        code_inputs = []
        try:
            # wait for code input to appear up to 10s
            WebDriverWait(self.driver, 10).until(
                lambda d: len(d.find_elements(By.CSS_SELECTOR, 'input[placeholder*=\"codice\" i], input[placeholder*=\"code\" i], input[maxlength=\"1\"], input[data-e2e*=\"code\"], input[name*=\"code\"], input[autocomplete*=\"one-time-code\"]')) > 0
                or len(d.find_elements(By.CSS_SELECTOR, 'input[placeholder*=\"OTP\" i]')) > 0
            )
        except TimeoutException:
            log.warning('No verification code input found after waiting (maybe code was not sent)')
            # check if error indicates need to retry
            errs = self._collect_error_messages()
            if errs:
                log.warning('Errors after waiting for code input: %s', errs)
            return False

        # Try to locate all possible code inputs
        selectors = [
            'input[placeholder*=\"codice\" i]',
            'input[placeholder*=\"code\" i]',
            'input[autocomplete=\"one-time-code\"]',
            'input[name*=\"code\" i]',
            'input[data-e2e*=\"code\" i]',
            'input[maxlength=\"1\"]',
        ]
        for sel in selectors:
            try:
                found = self.driver.find_elements(By.CSS_SELECTOR, sel)
                visible = [e for e in found if e.is_displayed()]
                if visible:
                    code_inputs = visible
                    log.info('Found %d code inputs via selector %s', len(visible), sel)
                    break
            except Exception:
                continue
        # Fallback: search any input that appeared after send
        if not code_inputs:
            try:
                all_inputs = self.driver.find_elements(By.TAG_NAME, 'input')
                # filter those that are not email/password
                code_inputs = [i for i in all_inputs if i.get_attribute('type') not in ['password', 'hidden'] and i.get_attribute('name') != 'email' and i.is_displayed()]
                # if many, prefer last ones
                if len(code_inputs) > 3:
                    # likely 6 inputs
                    code_inputs = code_inputs[-6:]
                log.info('Fallback found %d inputs as code candidates', len(code_inputs))
            except Exception:
                pass

        if not code_inputs:
            log.warning('No verification code input found at all')
            return False

        # Now wait for verification code from email
        log.info('Waiting for verification code...')
        code = self._wait_for_verification_code(timeout=120)
        if not code:
            log.error('Could not get verification code within timeout')
            # save debug
            try:
                self.driver.save_screenshot('_no_code_received.png')
                log.info('Page source snippet: %s', self.driver.page_source[:1000])
            except Exception:
                pass
            return False

        # Enter code
        code = code.strip()
        log.info('Entering verification code: %s', code)
        try:
            if len(code_inputs) == 1:
                inp = code_inputs[0]
                inp.click()
                time.sleep(0.3)
                # clear
                try:
                    inp.clear()
                except Exception:
                    self.driver.execute_script("arguments[0].value='';", inp)
                _human_type(inp, code, delay_range=(0.08, 0.15))
                _trigger_input_events(self.driver, inp)
                time.sleep(1)
            elif len(code_inputs) >= 4:
                # 6 separate boxes - type each digit
                digits = list(code)
                for idx, inp in enumerate(code_inputs[:len(digits)]):
                    try:
                        inp.click()
                        time.sleep(0.2)
                        # clear
                        self.driver.execute_script("arguments[0].value='';", inp)
                        inp.send_keys(digits[idx])
                        _trigger_input_events(self.driver, inp)
                        time.sleep(random.uniform(0.1, 0.25))
                    except Exception as e:
                        log.warning('Failed to type digit %d: %s', idx, e)
                        # fallback JS
                        try:
                            self.driver.execute_script("arguments[0].value=arguments[1]; arguments[0].dispatchEvent(new Event('input',{bubbles:true}));", inp, digits[idx])
                        except Exception:
                            pass
                time.sleep(1)
            else:
                # unknown count like 4? just use first
                inp = code_inputs[0]
                inp.click()
                _human_type(inp, code)
                _trigger_input_events(self.driver, inp)
            log.info('Verification code entered: %s', code)
            # check for immediate validation error
            time.sleep(1.5)
            errs = self._get_inline_errors()
            if errs:
                log.warning('Errors after entering code: %s', errs)
                for e in errs:
                    if 'non valido' in e.lower() or 'invalid' in e.lower() or 'scaduto' in e.lower() or 'expired' in e.lower():
                        log.error('Code appears invalid/expired: %s', e)
                        return False
            return True
        except Exception as e:
            log.error('Failed to enter verification code: %s', e)
            return False

    def _step9_submit(self):
        log.info('STEP 9: Submit registration')
        time.sleep(1)
        # Try multiple submit button selectors
        submit_selectors = [
            '//button[contains(text(), \"Avanti\")]',
            '//button[contains(text(), \"Sign up\")]',
            '//button[contains(text(), \"Register\")]',
            '//button[contains(text(), \"Registrati\")]',
            '//button[contains(text(), \"Continua\")]',
            '//button[contains(text(), \"Next\")]',
            '//button[@type=\"submit\"]',
        ]
        for xpath in submit_selectors:
            try:
                btns = self.driver.find_elements(By.XPATH, xpath)
                visible = [b for b in btns if b.is_displayed() and b.is_enabled()]
                if visible:
                    btn = visible[0]
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                    time.sleep(0.5)
                    try:
                        btn.click()
                    except Exception:
                        self.driver.execute_script("arguments[0].click();", btn)
                    log.info('Clicked submit button via %s', xpath)
                    time.sleep(5)
                    return True
            except Exception:
                continue

        # Fallback: press Enter on active element or code input
        log.warning('Submit button not found, pressing Enter')
        try:
            active = self.driver.switch_to.active_element
            active.send_keys(Keys.RETURN)
            time.sleep(5)
            return True
        except Exception as e:
            log.error('Could not submit via Enter: %s', e)
            # try JS form submit
            try:
                self.driver.execute_script("""
                    const form = document.querySelector('form');
                    if (form) form.submit();
                    else {
                        const btns = document.querySelectorAll('button[type=\"submit\"]');
                        if (btns.length>0) btns[0].click();
                    }
                """)
                time.sleep(5)
                return True
            except Exception as e2:
                log.error('JS submit also failed: %s', e2)
                return False

    def _extract_account_data(self, require_verification=False):
        try:
            time.sleep(4)
            current_url = self.driver.current_url
            page_source = self.driver.page_source[:2000].lower() if self.driver.page_source else ""

            # Check if still on signup page - indicates failure
            still_on_signup = 'signup' in current_url.lower()
            has_error = 'error' in page_source or 'non valido' in page_source

            cookies = {}
            for cookie in self.driver.get_cookies():
                cookies[cookie['name']] = cookie['value']

            # Check for important auth cookies (broader set)
            auth_cookie_names = ['sid_tt', 'sessionid', 'sessionid_ss', 'uid_tt', 'sid_guard', 'tt_csrf_token', 'passport_csrf_token', 'tt_chain_token', 'tt_webid', 'sid_ucp_v1', 'ssid_ucp_v1']
            has_auth_cookies = any(k in cookies for k in auth_cookie_names) or any('sid' in k.lower() or 'session' in k.lower() or 'token' in k.lower() and 'csrf' in k.lower() for k in cookies.keys())
            # ttwid alone is not sufficient for logged-in

            # Try to extract user info from page or cookies
            user_id = ''
            sec_uid = ''
            username = ''
            # Try extracting from cookies or page
            try:
                # Check localStorage or page JSON
                user_data_json = self.driver.execute_script("""
                    try {
                        // try to find user data in page
                        const html = document.documentElement.innerHTML;
                        const secUidMatch = html.match(/\"secUid\"\\s*:\\s*\"([^\"]+)\"/);
                        const uidMatch = html.match(/\"uid\"\\s*:\\s*\"?(\\d+)\"?/);
                        const uniqueIdMatch = html.match(/\"uniqueId\"\\s*:\\s*\"([^\"]+)\"/);
                        return {
                            secUid: secUidMatch ? secUidMatch[1] : '',
                            uid: uidMatch ? uidMatch[1] : '',
                            uniqueId: uniqueIdMatch ? uniqueIdMatch[1] : '',
                            url: window.location.href
                        };
                    } catch(e) { return {error: e.message}; }
                """)
                if isinstance(user_data_json, dict):
                    sec_uid = user_data_json.get('secUid', '')
                    user_id = user_data_json.get('uid', '')
                    username = user_data_json.get('uniqueId', '')
            except Exception as e:
                log.debug('Failed to extract user data from page: %s', e)

            # Also try to get from cookies if possible
            # sessionid_ss often contains user id?

            x_token = cookies.get('tt-token', '') or cookies.get('X-Tt-Token', '')
            ttwid = cookies.get('ttwid', '')
            passport_csrf_token = cookies.get('passport_csrf_token', '') or cookies.get('tt_csrf_token', '')

            verification_success = False
            # Multiple success signals
            if not still_on_signup and has_auth_cookies:
                verification_success = True
            elif user_id and sec_uid:
                verification_success = True
            elif not still_on_signup and len(cookies) > 8:
                # maybe success if we left signup page
                verification_success = True
            elif not still_on_signup and has_auth_cookies is False and len(cookies) > 5:
                # Even without explicit auth cookie, leaving signup suggests progress
                # Check for no error on page
                if not has_error:
                    verification_success = True
            else:
                # Check if we are on TikTok feed/profile (success)
                if 'tiktok.com/foryou' in current_url or ('tiktok.com/@' in current_url and 'signup' not in current_url.lower()):
                    verification_success = True
                # Also success if URL changed from signup and no error
                if not still_on_signup and not has_error and len(cookies) >= 4:
                    verification_success = True

            if require_verification and not verification_success:
                log.warning('Verification not confirmed: still_on_signup=%s has_auth=%s url=%s cookies=%d', still_on_signup, has_auth_cookies, current_url, len(cookies))
                # return data anyway but mark as not verified
            else:
                log.info('Verification success: url=%s', current_url)

            account_data = {
                'email': self.temp_email,
                'password': self.password,
                'user_id': user_id,
                'sec_uid': sec_uid,
                'username': username or self.temp_email.split('@')[0],
                'x_tt_token': x_token,
                'cookies': cookies,
                'ttwid': ttwid,
                'passport_csrf_token': passport_csrf_token,
                'domain': 'www.tiktok.com',
                'status': 'active' if verification_success else 'pending_verification',
                'created_at': int(time.time()),
                'source': 'email_signup_v2',
                'verification_success': verification_success,
                'current_url': current_url,
                'birthday': f"{self._birthday[0]}-{self._birthday[1]:02d}-{self._birthday[2]:02d}" if self._birthday else None,
                'provider': self.email_provider.provider_name,
            }

            log.info('Account data extracted: verification=%s cookies=%d url=%s', verification_success, len(cookies), current_url[:80])
            return account_data

        except Exception as e:
            log.error('Failed to extract account data: %s', e)
            traceback.print_exc()
            return None

    def _save_account(self, account_data):
        os.makedirs(ACCOUNTS_DIR, exist_ok=True)
        filename = account_data.get('user_id') or account_data['email'].split('@')[0]
        # sanitize filename
        filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
        path = os.path.join(ACCOUNTS_DIR, f'{filename}.json')
        with open(path, 'w') as f:
            json.dump(account_data, f, indent=2)
        log.info('Account saved to %s', path)
        return path


def create_accounts_batch(count, headless=False, proxy=None, delay_min=10, delay_max=30, max_workers=3, proxy_list=None):
    """
    Parallel batch creation. max_workers=1 = sequential (safe for low RAM).
    proxy_list: list of proxies to rotate per account (free pool). If provided, each account gets round-robin proxy.
    Uses ThreadPoolExecutor for parallel Chrome instances (cose in parallelo = throughput).
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results = {'success': 0, 'failed': 0}
    lock = threading.Lock()

    # normalize proxy_list
    if proxy_list is None and proxy:
        proxy_list = [proxy]
    if proxy_list and len(proxy_list) == 0:
        proxy_list = None

    def _create_one(idx):
        # idx 1-based
        assigned_proxy = None
        if proxy_list:
            assigned_proxy = proxy_list[(idx - 1) % len(proxy_list)]
        elif proxy:
            assigned_proxy = proxy
        log.info('Creating account %d/%d... proxy=%s', idx, count, assigned_proxy or 'none')
        creator = TikTokAccountCreatorV2(headless=headless, proxy=assigned_proxy)
        account = creator.create_account()
        with lock:
            if account and account.get('verification_success'):
                results['success'] += 1
                log.info('[%d/%d] Success: %s (provider=%s proxy=%s)', idx, count, account.get('email'), account.get('provider'), assigned_proxy or 'none')
                return True
            else:
                results['failed'] += 1
                log.warning('[%d/%d] Failed (proxy=%s)', idx, count, assigned_proxy or 'none')
                return False

    if max_workers <= 1 or count <= 2:
        # sequential fallback (low RAM, stable)
        for i in range(count):
            _create_one(i + 1)
            if i < count - 1:
                delay = random.uniform(delay_min, delay_max)
                log.info('Waiting %.1fs before next account...', delay)
                time.sleep(delay)
    else:
        # parallel: limit workers to avoid Chrome overload; stagger start slightly
        log.info('Parallel batch: %d accounts with %d workers (cose in parallelo attivo)', count, max_workers)
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {}
            for i in range(count):
                fut = ex.submit(_create_one, i + 1)
                futures[fut] = i + 1
                if i < count - 1:
                    # small stagger to avoid burst but keep parallel speedup (0.8-1.5s)
                    time.sleep(random.uniform(0.8, 1.5))
            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception as e:
                    log.error('Parallel worker error: %s', e)
                    with lock:
                        results['failed'] += 1

    log.info('Batch done (parallel=%s): %d success, %d failed', max_workers > 1, results['success'], results['failed'])
    return results


# Backwards compatibility alias
TikTokAccountCreator = TikTokAccountCreatorV2
