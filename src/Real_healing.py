# ============================================================
# Real_healing.py  ―  힐링모드
#   · 시간대별 LED 색온도 제어 + 격려 음성 재생
#   · 모션 기반 수면 추적 → MySQL 저장 (상담자 원격 조회)
#   · 태양 고도(ephem) 기반 서보 블라인드 제어
# ============================================================
import ephem            # 태양 고도 계산
import datetime
import RPi.GPIO as GPIO  # 모터, LED 제어
import time
import pymysql          # 데이터베이스
import pygame           # 음원 재생
import random
import cv2              # 영상 처리
import mediapipe as mp  # 수면 여부 판단
import math

# ── GPIO / PWM 초기화 ──
servo_pin_1 = 18
servo_pin_2 = 23
led_blue = 21
led_white = 20
led_orange = 12

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(servo_pin_1, GPIO.OUT)
GPIO.setup(servo_pin_2, GPIO.OUT)
GPIO.setup(led_blue, GPIO.OUT)
GPIO.setup(led_white, GPIO.OUT)
GPIO.setup(led_orange, GPIO.OUT)

pwm_1 = GPIO.PWM(servo_pin_1, 50)
pwm_2 = GPIO.PWM(servo_pin_2, 50)
pwm_1.start(0)
pwm_2.start(0)

# ── 데이터베이스 설정 ──
# NOTE: 원본은 음원용 DB('mp3files')와 수면로그용 DB('mydb')를 함께 사용합니다.
DB_HOST = 'localhost'
DB_USER = 'root'
DB_PASSWORD = 'YOUR_DB_PASSWORD'   # TODO: 실제 비밀번호는 커밋 금지
DB_NAME = 'mp3files'

# ── pygame 초기화 ──
pygame.init()
pygame.mixer.init()


# ─────────────────────────────────────────────────────────
# ⚠️ 아래 두 함수는 PPT에 정의가 없어 "예시"로 채운 것입니다.
#    (호출부만 있고 본체가 발표자료에 없었음 → 원본으로 교체 필요)
# ─────────────────────────────────────────────────────────
def get_solar_altitude(latitude, longitude):
    """[예시 구현] 현재 태양 고도(도)를 반환. 원본과 다를 수 있음."""
    obs = ephem.Observer()
    obs.lat = str(latitude)
    obs.lon = str(longitude)
    obs.date = datetime.datetime.utcnow()
    sun = ephem.Sun(obs)
    return math.degrees(float(sun.alt))   # 라디안 → 도


def angle_to_duty_cycle(angle):
    """[예시 구현] 서보 각도(0~180°)를 PWM 듀티사이클로 변환. 원본과 다를 수 있음."""
    angle = max(0, min(180, angle))       # 범위 클램프
    return 2.0 + (angle / 18.0)           # 통상적인 SG/MG 서보 매핑


# ─────────────────────────────────────────────────────────
# 음원 / LED 제어 함수
# ─────────────────────────────────────────────────────────
def get_music_file_by_id(file_id):
    conn = pymysql.connect(host=DB_HOST, user=DB_USER,
                           password=DB_PASSWORD, database=DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT filepath FROM files WHERE id = %s", (file_id,))
    file = cursor.fetchone()
    cursor.close()
    conn.close()
    return file[0] if file else None


def play_music(file, duration):
    try:
        pygame.mixer.music.load(file)
        pygame.mixer.music.play()
        start_time = time.time()
        while pygame.mixer.music.get_busy() and time.time() - start_time < duration:
            time.sleep(0.1)
        pygame.mixer.music.stop()
    except pygame.error as e:
        print(f"Could not play the music file {file}: {e}")


def play_track_and_wait(track_ids, duration):
    track_id = random.choice(track_ids)
    track_file = get_music_file_by_id(track_id)
    if track_file:
        print(f"Playing track: {track_file}")
        play_music(track_file, duration)
    else:
        print(f"No track found for ID {track_id}")


def control_leds(current_hour, awake, person_detected):
    """시간대별 LED 색온도 제어 (오전 파랑 / 오후 흰색 / 저녁 주황)."""
    if not person_detected or not awake:
        GPIO.output(led_blue, GPIO.LOW)
        GPIO.output(led_white, GPIO.LOW)
        GPIO.output(led_orange, GPIO.LOW)
    else:
        if 9 <= current_hour < 12:
            GPIO.output(led_blue, GPIO.HIGH)
            GPIO.output(led_white, GPIO.LOW)
            GPIO.output(led_orange, GPIO.LOW)
        elif 12 <= current_hour < 18:
            GPIO.output(led_blue, GPIO.LOW)
            GPIO.output(led_white, GPIO.HIGH)
            GPIO.output(led_orange, GPIO.LOW)
        elif 18 <= current_hour < 23:
            GPIO.output(led_blue, GPIO.LOW)
            GPIO.output(led_white, GPIO.LOW)
            GPIO.output(led_orange, GPIO.HIGH)
        else:
            GPIO.output(led_blue, GPIO.LOW)
            GPIO.output(led_white, GPIO.LOW)
            GPIO.output(led_orange, GPIO.LOW)


# ─────────────────────────────────────────────────────────
# 수면 추적 / 모션 감지 설정
# ─────────────────────────────────────────────────────────
mp_drawing = mp.solutions.drawing_utils
mp_holistic = mp.solutions.holistic

cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
time.sleep(2.0)

motion_detected = False
motion_start_time = 0
background = None
sleep_timer = 0
sleep_duration = 10
awake_duration = 10
awake = True
total_sleep_time = 0
last_sleep_check = None
start_time = datetime.datetime.now()
sleep_start_time = None


def is_time_to_upload(accelerated_time):
    return accelerated_time.hour == 16 and accelerated_time.minute == 0


def detect_motion(frame, background, threshold=50):
    """배경 프레임과의 차분으로 움직임 유무를 판단."""
    global motion_detected, motion_start_time

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (21, 21), 0)

    if background is None:
        return gray, False

    frame_delta = cv2.absdiff(background, gray)
    thresh = cv2.threshold(frame_delta, threshold, 255, cv2.THRESH_BINARY)[1]
    thresh = cv2.dilate(thresh, None, iterations=2)
    contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    motion_detected = False
    for contour in contours:
        if cv2.contourArea(contour) > 500:
            motion_detected = True
            return gray, True
    return gray, motion_detected


def save_sleep_data(date, sleep_start, sleep_end, total_sleep):
    """하루 수면 데이터를 수면로그 DB(mydb.sleep_log)에 저장."""
    conn = pymysql.connect(host='localhost', user='root',
                           password=DB_PASSWORD, db='mydb', charset='utf8')
    c = conn.cursor()
    query = ('INSERT INTO sleep_log (date, sleep_start, sleep_end, total_sleep) '
             'VALUES (%s, %s, %s, %s)')
    c.execute(query, (date, sleep_start, sleep_end, total_sleep))
    conn.commit()
    conn.close()


# ── 메인 루프 설정 ──
observer_latitude = 37.3259
observer_longitude = 126.5801

morning_ids = [1, 4, 6]
afternoon_ids = [2, 3, 8]
night_ids = [5, 7]

frame_skip = 10
frame_count = 0
acceleration_factor = 288   # 하루(24h)를 30분으로 축약 (288배속)


# ─────────────────────────────────────────────────────────
# 메인 루프
# ─────────────────────────────────────────────────────────
try:
    with mp_holistic.Holistic(min_detection_confidence=0.5,
                              min_tracking_confidence=0.5) as holistic:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            frame_count += 1
            if frame_count % frame_skip != 0:
                continue

            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = holistic.process(frame_rgb)
            person_detected = results.pose_landmarks is not None

            # 모션 감지 및 배경 갱신
            background, motion = detect_motion(frame, background)

            # 가속 시간 계산 (하루를 30분으로 축약)
            current_time = datetime.datetime.now()
            elapsed_time = (current_time - start_time).total_seconds()
            accelerated_time = start_time + datetime.timedelta(seconds=elapsed_time * acceleration_factor)

            # 태양 고도 → 서보(블라인드) PWM 제어
            solar_altitude = get_solar_altitude(observer_latitude, observer_longitude)
            pwm_1.ChangeDutyCycle(angle_to_duty_cycle(solar_altitude))
            pwm_2.ChangeDutyCycle(angle_to_duty_cycle(-solar_altitude))

            current_hour = accelerated_time.hour
            current_minute = accelerated_time.minute
            print(f"Current time: {current_hour}:{current_minute}")

            # 시간대별 격려 음성 재생
            if 8 <= current_hour < 9 and current_minute < 30:
                print("Playing morning track")
                play_track_and_wait(morning_ids, 30 * 60 / acceleration_factor)
            elif 12 <= current_hour < 13 and current_minute < 30:
                print("Playing afternoon track")
                play_track_and_wait(afternoon_ids, 30 * 60 / acceleration_factor)
            elif 18 <= current_hour < 19 and current_minute < 30:
                print("Playing night track")
                play_track_and_wait(night_ids, 30 * 60 / acceleration_factor)

            # 시간대 + 상태에 따른 LED 제어
            control_leds(current_hour, awake, person_detected)

            # 수면 상태 판단
            if person_detected and not motion_detected:
                if time.time() - sleep_timer >= sleep_duration:
                    cv2.putText(frame, "Sleeping", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                    awake = False
                    if sleep_start_time is None:
                        sleep_start_time = accelerated_time
                else:
                    cv2.putText(frame, "Awake", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                    awake = True
            elif person_detected:
                cv2.putText(frame, "Awake", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                sleep_timer = time.time()
                awake = True
                if sleep_start_time is not None:
                    sleep_end_time = accelerated_time
                    total_sleep_time += (sleep_end_time - sleep_start_time).total_seconds()
                    sleep_start_time = None
            else:
                cv2.putText(frame, "No person detected", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)
                awake = True

            # 자는 중 움직임 감지 시 기상 처리
            if not awake and motion:
                if motion_start_time == 0:
                    motion_start_time = time.time()
                elif time.time() - motion_start_time >= awake_duration:
                    awake = True
            else:
                motion_start_time = 0

            # 수면 시간 누적
            if person_detected and not awake:
                if last_sleep_check is not None:
                    total_sleep_time += (accelerated_time - last_sleep_check).total_seconds()
                last_sleep_check = accelerated_time
            else:
                last_sleep_check = None

            cv2.putText(frame, f"Total Sleep Time: {total_sleep_time / 3600:.2f} hours",
                        (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            cv2.putText(frame, f"Current Time: {accelerated_time.strftime('%Y-%m-%d %H:%M:%S')}",
                        (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            # 지정 시각(오후 4시)에 수면 데이터 DB 업로드
            if is_time_to_upload(accelerated_time):
                if total_sleep_time > 0:
                    date = start_time.strftime("%Y-%m-%d")
                    sleep_start = sleep_start_time.strftime("%H:%M:%S") if sleep_start_time else None
                    sleep_end = accelerated_time.strftime("%H:%M:%S")
                    save_sleep_data(date, sleep_start, sleep_end, total_sleep_time / 3600)
                    total_sleep_time = 0
                    sleep_start_time = None

            cv2.imshow("Frame", frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

finally:
    pwm_1.stop()
    pwm_2.stop()
    GPIO.cleanup()
    pygame.quit()
    cap.release()
    cv2.destroyAllWindows()
