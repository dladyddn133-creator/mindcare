# ============================================================
# Real_main.py  ―  집중/힐링 모드 전환 런처
# ------------------------------------------------------------
#    실제 라즈베리파이에서 돌렸던 원본과 세부가 다를 수 있습니다.
# ============================================================
import RPi.GPIO as GPIO   # 라즈베리파이 GPIO 제어
import time               # 시간 지연
import subprocess         # 외부 스크립트 실행
import os                 # OS 기능 (미사용 시 제거 가능)

# ── 버튼 핀 설정 ──
button_pin_1 = 27   # 스위치 1 (집중모드)
button_pin_2 = 19   # 스위치 2 (힐링모드)

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(button_pin_1, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(button_pin_2, GPIO.IN, pull_up_down=GPIO.PUD_UP)

prev_state_1 = GPIO.input(button_pin_1)
prev_state_2 = GPIO.input(button_pin_2)

# ── 실행할 스크립트 경로 ──
focus_script = "/home/dladyddn144/Real_Study.py"
healing_script = "/home/dladyddn144/Real_healing.py"

current_process = None   # 현재 실행 중인 프로세스


def terminate_current_process():
    """현재 실행 중인 모드 스크립트를 종료한다."""
    global current_process
    if current_process is not None:
        try:
            current_process.terminate()
            current_process.wait()
        except subprocess.SubprocessError as e:
            print(f"Error terminating process: {e}")
        current_process = None


try:
    while True:
        current_state_1 = GPIO.input(button_pin_1)
        current_state_2 = GPIO.input(button_pin_2)

        # 스위치 1 눌림 → 집중모드
        if prev_state_1 == GPIO.HIGH and current_state_1 == GPIO.LOW:
            print("Entering Focus Mode")
            terminate_current_process()
            time.sleep(0.5)   # 종료 대기
            current_process = subprocess.Popen(["python3", focus_script])

        # 스위치 2 눌림 → 힐링모드
        if prev_state_2 == GPIO.HIGH and current_state_2 == GPIO.LOW:
            print("Entering Healing Mode")
            terminate_current_process()
            time.sleep(0.5)
            current_process = subprocess.Popen(["python3", healing_script])

        prev_state_1 = current_state_1
        prev_state_2 = current_state_2
        time.sleep(0.1)

except KeyboardInterrupt:
    print("Exiting program")
    terminate_current_process()

finally:
    GPIO.cleanup()
