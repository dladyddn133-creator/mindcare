-- ============================================================
-- schema.sql  ―  마음챙김 프로젝트 DB 스키마 
-- ============================================================

-- ── 수면 로그 DB (Real_healing.py: save_sleep_data / de_test2.php) ──
CREATE DATABASE IF NOT EXISTS mydb;
USE mydb;

CREATE TABLE IF NOT EXISTS sleep_log (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    date         DATE,
    sleep_start  TIME,
    sleep_end    TIME,
    total_sleep  FLOAT          -- 단위: 시간(hours)
);

-- ── 음원 DB (Real_healing.py: get_music_file_by_id) ──
CREATE DATABASE IF NOT EXISTS mp3files;
USE mp3files;

CREATE TABLE IF NOT EXISTS files (
    id        INT PRIMARY KEY,  -- morning/afternoon/night 트랙 ID 
    filepath  VARCHAR(255)      -- mp3 파일 경로
);

-- 예시 데이터 (경로는 실제 파일 위치로 교체)
-- INSERT INTO files (id, filepath) VALUES
--   (1, '/home/pi/tracks/morning_1.mp3'),
--   (2, '/home/pi/tracks/afternoon_1.mp3');
