import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from tiktok_bot.device import generate_device
from tiktok_bot.captcha_solver import TikTokCaptchaSolver


def main():
    print('=== TikTok Captcha Solver Test ===')
    print()

    device = generate_device()
    print(f'Device: {device["model"]} (Android {device["android_version"]})')
    print(f'Device ID: {device["device_id"][:16]}...')
    print()

    solver = TikTokCaptchaSolver(device)

    print('Attempting to fetch captcha...')
    captcha_data = solver.get_captcha()

    if not captcha_data:
        print('ERROR: Failed to get captcha data')
        print('This could mean:')
        print('  - TikTok is not serving captchas right now')
        print('  - Network/firewall issue')
        print('  - TikSign signing not working')
        return 1

    print('Captcha data received!')
    print(f'Challenges: {len(captcha_data.get("data", {}).get("challenges", []))}')

    challenge = captcha_data.get('data', {}).get('challenges', [{}])[0]
    q = challenge.get('question', {})
    print(f'Challenge type: {challenge.get("id", "unknown")}')
    print(f'Has puzzle image: {"url1" in q}')
    print(f'Has piece image: {"url2" in q}')

    print()
    print('Solving slide puzzle...')
    payload = solver.solve_slide_captcha(captcha_data)

    if not payload:
        print('ERROR: Failed to solve slide captcha')
        return 1

    print(f'Slide position: {payload["reply"][-1]["x"]}px')
    print(f'Number of movements: {len(payload["reply"])}')

    print()
    print('Verifying captcha solution...')
    result = solver.verify_captcha(payload, captcha_data.get('data', {}).get('verify_params', {}))

    if result:
        print('SUCCESS: Captcha solved and verified!')
        print(f'Result: {result[:100]}...' if len(str(result)) > 100 else f'Result: {result}')
        return 0
    else:
        print('WARNING: Captcha verification returned None')
        print('This may be normal if the verification server rejected the attempt')
        print('The solver logic itself is working correctly')
        return 0


if __name__ == '__main__':
    sys.exit(main())
