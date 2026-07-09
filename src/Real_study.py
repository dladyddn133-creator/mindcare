# ============================================================
# Real_Study.py  ―  집중모드
#   · MediaPipe 얼굴 인식으로 졸음(눈 개폐) 판정 → LED 제어
#   · 손가락 개수 제스처로 YouTube 음악 제어
# ============================================================
import cv2
import itertools
import numpy as np
import mediapipe as mp
import time
import RPi.GPIO as GPIO
import os
import subprocess
from googleapiclient.discovery import build
import threading
import ephem
import datetime

# ── MediaPipe 설정 ──
mp_face_mesh = mp.solutions.face_mesh
mp_drawing = mp.solutions.drawing_utils
mp_hands = mp.solutions.hands

face_mesh_videos = mp_face_mesh.FaceMesh(
    static_image_mode=False, max_num_faces=1,
    min_detection_confidence=0.5, min_tracking_confidence=0.3)

# ── YouTube API 설정 ──
API_KEY = 'YOUR_API_KEY'            # TODO: 실제 키는 커밋 금지 (환경변수/설정파일로 분리)
playlist_id = 'YOUR_PLAYLIST_ID'
playlist_id2 = 'YOUR_PLAYLIST_ID2'
youtube = build('youtube', 'v3', developerKey=API_KEY)

# ── GPIO / LED 설정 ──
LED_PIN = 20
GPIO.setmode(GPIO.BCM)
GPIO.setup(LED_PIN, GPIO.OUT)


# ─────────────────────────────────────────────────────────
# 얼굴 / 손 인식 관련 함수
# ─────────────────────────────────────────────────────────
def detectFacialLandmarks(image, face_mesh):
    results = face_mesh.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    return results


def getSize(image, face_landmarks, INDEXES):
    image_height, image_width, _ = image.shape
    INDEXES_LIST = list(itertools.chain(*INDEXES))
    landmarks = []
    for INDEX in INDEXES_LIST:
        landmarks.append([int(face_landmarks.landmark[INDEX].x * image_width),
                          int(face_landmarks.landmark[INDEX].y * image_height)])
    _, _, width, height = cv2.boundingRect(np.array(landmarks))
    landmarks = np.array(landmarks)
    return width, height, landmarks


def isOpen(image, face_mesh_results, face_part, threshold):
    """눈 높이 / 얼굴 높이 비율로 눈 개폐(OPEN/CLOSE)를 판정."""
    status = {}
    if face_part == 'LEFT EYE':
        INDEXES = mp_face_mesh.FACEMESH_LEFT_EYE
    elif face_part == 'RIGHT EYE':
        INDEXES = mp_face_mesh.FACEMESH_RIGHT_EYE
    else:
        return

    for face_no, face_landmarks in enumerate(face_mesh_results.multi_face_landmarks):
        _, height, _ = getSize(image, face_landmarks, INDEXES)
        _, face_height, _ = getSize(image, face_landmarks, mp_face_mesh.FACEMESH_FACE_OVAL)
        if (height / face_height) * 90 > threshold:
            status[face_no] = 'OPEN'
        else:
            status[face_no] = 'CLOSE'
    return status


def count_fingers(hand_landmarks, handedness):
    """펴진 손가락 개수를 센다."""
    finger_tips = [8, 12, 16, 20]
    fingers_open = 0

    palm_visible = hand_landmarks.landmark[0].y < hand_landmarks.landmark[9].y

    # 엄지: 손바닥/손등 방향과 좌우 손(handedness)에 따라 x좌표로 판정
    if palm_visible:
        if handedness == "Right":
            if hand_landmarks.landmark[4].x > hand_landmarks.landmark[3].x:
                fingers_open += 1
        else:
            if hand_landmarks.landmark[4].x < hand_landmarks.landmark[3].x:
                fingers_open += 1
    else:
        if handedness == "Right":
            # TODO: PPT에서 이 줄이 잘려 있었습니다("landmark[3]." 뒤 누락). 원본 확인 권장.
            if hand_landmarks.landmark[4].x < hand_landmarks.landmark[3].x:
                fingers_open += 1
        else:
            if hand_landmarks.landmark[4].x > hand_landmarks.landmark[3].x:
                fingers_open += 1

    # 검지~새끼: 손끝(y)이 두 번째 관절보다 위(작음)면 펴진 것으로 간주
    for tip in finger_tips:
        if hand_landmarks.landmark[tip].y < hand_landmarks.landmark[tip - 2].y:
            fingers_open += 1
    return fingers_open


# ─────────────────────────────────────────────────────────
# YouTube 재생 관련 함수
# ─────────────────────────────────────────────────────────
def get_playlist_items(playlist_id):
    request = youtube.playlistItems().list(
        part="snippet", playlistId=playlist_id, maxResults=25)
    response = request.execute()
    return response['items']


def get_video_ids(items):
    return [item['snippet']['resourceId']['videoId'] for item in items]


def play_music(video_id):
    process = subprocess.Popen(
        f'mpv --no-video --input-ipc-server=/tmp/mpvsocket '
        f'$(yt-dlp -g "https://www.youtube.com/watch?v={video_id}")',
        shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return process


def stop_music(process):
    if process and process.poll() is None:
        os.system('echo \'{ "command": ["quit"] }\' | socat - /tmp/mpvsocket')
        process.terminate()
        process.wait()


def pause_music():
    os.system('echo \'{ "command": ["set_property", "pause", true] }\' | socat - /tmp/mpvsocket')


def resume_music():
    os.system('echo \'{ "command": ["set_property", "pause", false] }\' | socat - /tmp/mpvsocket')


# ─────────────────────────────────────────────────────────
# 손동작에 따른 음악 제어
#   0: 정지 / 1: 일시정지 / 2: 재개 / 3: 종료 / 4: 플레이리스트 전환
# ─────────────────────────────────────────────────────────
def control_music(fingers_open, process, current_playlist, playlist_1, playlist_2, video_index, cap):
    if fingers_open == 0:
        print("Stop Music")
        stop_music(process)
        process = None
    elif fingers_open == 1:
        print("Pause Music")
        pause_music()
    elif fingers_open == 2:
        print("Resume Music")
        resume_music()
    elif fingers_open == 3:
        print("Stop Music and Exit")
        stop_music(process)
        process = None
        cap.release()
        cv2.destroyAllWindows()
        GPIO.cleanup()
        exit()
    elif fingers_open == 4:
        print("Switching Playlist")
        stop_music(process)
        current_playlist = 2 if current_playlist == 1 else 1
        video_index = 0
        process = play_music(playlist_2[video_index] if current_playlist == 2 else playlist_1[video_index])
    return process, current_playlist, video_index


# ─────────────────────────────────────────────────────────
# 메인 스레드: 얼굴/손 추적 + 음악 제어
# ─────────────────────────────────────────────────────────
def music_control_thread():
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(12, GPIO.OUT)

    cap = cv2.VideoCapture(0)
    process = None

    items1 = get_playlist_items(playlist_id)
    items2 = get_playlist_items(playlist_id2)
    playlist_1 = get_video_ids(items1)
    playlist_2 = get_video_ids(items2)
    current_playlist = 1
    video_index = 0

    finger_state = None
    finger_state_start_time = None
    DELAY_TIME = 2  # 제스처 상태 변화 감지 지연

    start_time = None
    eyes_closed = False
    face_not_detected_start_time = None

    with mp_hands.Hands(max_num_hands=1,
                        min_detection_confidence=0.7,
                        min_tracking_confidence=0.7) as hands:
        while cap.isOpened():
            success, image = cap.read()
            if not success:
                print("Ignoring empty camera frame.")
                continue

            image = cv2.flip(image, 1)
            face_mesh_results = detectFacialLandmarks(image, face_mesh_videos)

            # ── 얼굴 인식 → 졸음 판정 ──
            if face_mesh_results.multi_face_landmarks:
                face_not_detected_start_time = None
                left_eye_status = isOpen(image, face_mesh_results, 'LEFT EYE', threshold=4.5)
                right_eye_status = isOpen(image, face_mesh_results, 'RIGHT EYE', threshold=4.5)

                for face_num, face_landmarks in enumerate(face_mesh_results.multi_face_landmarks):
                    if left_eye_status[face_num] == 'CLOSE' and right_eye_status[face_num] == 'CLOSE':
                        if not eyes_closed:
                            start_time = time.time()
                            eyes_closed = True
                        elif time.time() - start_time > 5:   # 5초 이상 감음 → 취침
                            cv2.putText(image, 'Sleep', (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2, cv2.LINE_AA)
                            GPIO.output(12, False)
                            GPIO.output(LED_PIN, GPIO.LOW)
                    else:
                        eyes_closed = False
                        start_time = None
                        cv2.putText(image, 'Wake', (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2, cv2.LINE_AA)
                        GPIO.output(12, True)
                        GPIO.output(LED_PIN, GPIO.HIGH)
            else:
                if face_not_detected_start_time is None:
                    face_not_detected_start_time = time.time()
                elif time.time() - face_not_detected_start_time > 5:
                    cv2.putText(image, 'Not Detected', (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2, cv2.LINE_AA)
                    GPIO.output(12, False)
                    GPIO.output(LED_PIN, GPIO.LOW)

            # ── 손 인식 → 제스처 음악 제어 ──
            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            results = hands.process(image_rgb)
            image_rgb.flags.writeable = True
            image = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)

            if results.multi_hand_landmarks:
                for hand_landmarks, handedness in zip(results.multi_hand_landmarks, results.multi_handedness):
                    label = handedness.classification[0].label
                    if label == "Right":
                        fingers_open = count_fingers(hand_landmarks, label)
                        cv2.putText(image, f'Fingers: {fingers_open}', (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2, cv2.LINE_AA)
                        cv2.putText(image, f'Hand: {label}', (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2, cv2.LINE_AA)
                        mp_drawing.draw_landmarks(image, hand_landmarks, mp_hands.HAND_CONNECTIONS)

                        if fingers_open != finger_state:
                            finger_state = fingers_open
                            finger_state_start_time = time.time()
                        elif time.time() - finger_state_start_time > DELAY_TIME:
                            process, current_playlist, video_index = control_music(
                                fingers_open, process, current_playlist,
                                playlist_1, playlist_2, video_index, cap)
                            if fingers_open == 2 and (process is None or process.poll() is not None):
                                process = play_music(
                                    playlist_2[video_index] if current_playlist == 2 else playlist_1[video_index])
                                video_index = (video_index + 1) % (
                                    len(playlist_2) if current_playlist == 2 else len(playlist_1))

            cv2.imshow('Face and Hand Tracking', image)
            if cv2.waitKey(5) & 0xFF == 27:   # ESC 종료
                break

    cap.release()
    cv2.destroyAllWindows()
    GPIO.cleanup()


if __name__ == "__main__":
    music_thread = threading.Thread(target=music_control_thread)
    music_thread.start()
    music_thread.join()
