-- Điểm GPS đã preprocess (output của preprocess/v_<n>), mỗi user một dãy theo thời gian.
-- Nạp bằng `python -m geolife_api.seed`; nguồn sự thật là points.parquet, bảng này nạp lại được bất cứ lúc nào.

CREATE TABLE users (
    user_id  integer PRIMARY KEY,
    split    text NOT NULL CHECK (split IN ('dev', 'holdout')),
    n_points integer,           -- điền sau khi nạp điểm
    first_ts timestamptz,
    last_ts  timestamptz
);

CREATE TABLE gps_points (
    user_id  integer NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    ts_utc   timestamptz NOT NULL,
    ts_local timestamp NOT NULL,  -- giờ local theo timezone của toạ độ (đã tính ở preprocess)
    tz       text NOT NULL,       -- timezone IANA của toạ độ
    lat      double precision NOT NULL,
    lon      double precision NOT NULL,
    PRIMARY KEY (user_id, ts_utc) -- cũng là index cho truy vấn theo (user, khoảng thời gian)
);
