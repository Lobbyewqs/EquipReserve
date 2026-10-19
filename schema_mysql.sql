CREATE TABLE IF NOT EXISTS app_user (
 id BIGINT PRIMARY KEY AUTO_INCREMENT, username VARCHAR(191) NOT NULL UNIQUE,
 password_hash VARCHAR(200) NOT NULL, role VARCHAR(10) NOT NULL,
 enabled TINYINT NOT NULL DEFAULT 1, CHECK(role IN ('USER','ADMIN'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
CREATE TABLE IF NOT EXISTS device (
 id BIGINT PRIMARY KEY AUTO_INCREMENT, asset_code VARCHAR(64) NOT NULL UNIQUE,
 name VARCHAR(120) NOT NULL, category VARCHAR(60) NOT NULL,
 description TEXT NOT NULL DEFAULT (''), enabled TINYINT NOT NULL DEFAULT 1,
 current_loan_id BIGINT NULL, deleted_at VARCHAR(25) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
CREATE TABLE IF NOT EXISTS reservation (
 id BIGINT PRIMARY KEY AUTO_INCREMENT, user_id BIGINT NOT NULL, device_id BIGINT NOT NULL,
 slot_start VARCHAR(25) NOT NULL, slot_end VARCHAR(25) NOT NULL,
 pickup_deadline VARCHAR(25) NOT NULL, status VARCHAR(12) NOT NULL,
 borrowed_at VARCHAR(25), returned_at VARCHAR(25), created_at VARCHAR(25) NOT NULL,
 borrowed_device_id BIGINT GENERATED ALWAYS AS
   (CASE WHEN status='BORROWED' THEN device_id ELSE NULL END) VIRTUAL,
 UNIQUE KEY one_physical_loan (borrowed_device_id),
 KEY reservation_user_created (user_id,created_at),
 KEY reservation_expiry (status,pickup_deadline),
 KEY reservation_device_start (device_id,slot_start),
 FOREIGN KEY(user_id) REFERENCES app_user(id), FOREIGN KEY(device_id) REFERENCES device(id),
 CHECK(status IN ('CONFIRMED','CANCELLED','EXPIRED','BORROWED','RETURNED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
CREATE TABLE IF NOT EXISTS slot_occupancy (
 device_id BIGINT NOT NULL, slot_start VARCHAR(25) NOT NULL, reservation_id BIGINT NOT NULL UNIQUE,
 PRIMARY KEY(device_id,slot_start), FOREIGN KEY(device_id) REFERENCES device(id),
 FOREIGN KEY(reservation_id) REFERENCES reservation(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
CREATE TABLE IF NOT EXISTS idempotency_record (
 user_id BIGINT NOT NULL, operation VARCHAR(32) NOT NULL, request_key VARCHAR(128) NOT NULL,
 request_hash CHAR(64) NOT NULL, response_json LONGTEXT NOT NULL, response_code INT NOT NULL,
 PRIMARY KEY(user_id,operation,request_key), FOREIGN KEY(user_id) REFERENCES app_user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
CREATE TABLE IF NOT EXISTS audit_event (
 id BIGINT PRIMARY KEY AUTO_INCREMENT, actor_id BIGINT, action VARCHAR(64) NOT NULL,
 target_id BIGINT, before_state TEXT, after_state TEXT, reason TEXT,
 request_id VARCHAR(128) NOT NULL, created_at VARCHAR(25) NOT NULL,
 KEY audit_target_created (target_id,created_at), FOREIGN KEY(actor_id) REFERENCES app_user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
CREATE TABLE IF NOT EXISTS session (
 token_hash CHAR(64) PRIMARY KEY, user_id BIGINT NOT NULL, csrf VARCHAR(128) NOT NULL,
 expires_at VARCHAR(25) NOT NULL, FOREIGN KEY(user_id) REFERENCES app_user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
