/*
 * ============================================================
 *  SMART MOTO - ESP32 Full Firmware FINAL
 *  Tích hợp: v4 (ổn định) + vận tốc smooth 5Hz + SMS/gọi
 * ============================================================
 *  PIN MAP:
 *    NEO-6M  TX → GPIO4   (ESP32 RX1)
 *    NEO-6M  RX → GPIO2   (ESP32 TX1)
 *    A7682S  TX → GPIO16  (ESP32 RX2)
 *    A7682S  RX → GPIO17  (ESP32 TX2)
 *    MPU6050 SDA → GPIO21
 *    MPU6050 SCL → GPIO22
 *    BUZZER  → GPIO25
 *    LED1    → GPIO18
 *    LED2    → GPIO19
 * ============================================================
 */

#include <TinyGPS++.h>
#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>

HardwareSerial gpsSerial(1);   // UART1 → GPS  (RX=4, TX=2)
TinyGPSPlus      gps;
Adafruit_MPU6050 mpu;


const String LOCALTUNNEL_HOST = "smartmoto-minhdanqwertz-2026.loca.lt";
const String API_PATH         = "/api/update_location";
const String PHONE_NUMBER     = "+84983231501";
int          user_id          = 7;
// ────────────────────────────────────────────────────────────

#define BUZZER  25
#define LED1    18
#define LED2    19

// ─── THÔNG SỐ MPU & CẢNH BÁO ──────────────────────────────
const float THEFT_THRESHOLD = 8.0f;   // ngưỡng rung trộm
const float FALL_THRESHOLD  = 8.0f;   // ngưỡng phát hiện ngã
const long  ALARM_COOLDOWN  = 30000;  // 30 giây cooldown SMS/gọi

// ─── THÔNG SỐ GPS & VẬN TỐC ────────────────────────────────
const long  HTTP_INTERVAL   = 3000;   // gửi lên server mỗi 5 giây
const float SPEED_ZERO      = 1.0f;   // dưới 1.5 km/h → ép về 0 (giống file vantoc)
const float ALPHA           = 0.15f;   // hệ số Low-pass filter (0.1~1.0, càng nhỏ càng mượt)

// ─── BIẾN TRẠNG THÁI ───────────────────────────────────────
unsigned long lastHttpTime  = 0;
unsigned long lastAlarmTime = 0;
unsigned long prevLEDMillis = 0;
int           ledStep       = 0;
bool          is_theft      = false;
float         smoothSpeed   = 0.0f;   // vận tốc sau lọc Low-pass

// ══════════════════════════════════════════════════════════
//  AT COMMAND
// ══════════════════════════════════════════════════════════

String sendAT(String cmd, int timeout) {
    Serial2.println(cmd);
    Serial.println("[AT] >> " + cmd);
    String resp = "";
    unsigned long t = millis();
    while (millis() - t < (unsigned long)timeout) {
        while (Serial2.available()) resp += (char)Serial2.read();
    }
    if (resp.length()) Serial.println("[AT] << " + resp);
    return resp;
}

// ══════════════════════════════════════════════════════════
//  GỬI SMS
// ══════════════════════════════════════════════════════════

void sendSMS(String phone, String message) {
    Serial.println("[SMS] Dang gui SMS...");
    Serial2.println("AT+CMGF=1");
    delay(200);
    Serial2.print("AT+CMGS=\"" + phone + "\"\r");
    delay(200);
    Serial2.print(message);
    delay(200);
    Serial2.write(26); // Ctrl+Z
    delay(3000);
    Serial.println("[SMS] Da gui xong!");
}

// ══════════════════════════════════════════════════════════
//  GỌI ĐIỆN NHÁY MÁY
// ══════════════════════════════════════════════════════════

void makeCall(String phone) {
    Serial.println("[CALL] Dang goi...");
    Serial2.println("AT+CVOLTE=1");
    delay(100);
    Serial2.print("ATD" + phone + ";\r\n");
    Serial.println("[CALL] Dang do chuong 10 giay...");
    delay(10000);
    Serial2.println("ATH");
    Serial.println("[CALL] Da cup may!");
}

// ══════════════════════════════════════════════════════════
//  TĂNG TẦN SỐ GPS LÊN 5Hz (lệnh UBX từ file vantoc)
//  Giúp vận tốc cập nhật nhanh và mượt hơn nhiều
// ══════════════════════════════════════════════════════════

void setGPS5Hz() {
    byte updateRate5Hz[] = {
        0xB5, 0x62, 0x06, 0x08, 0x06, 0x00,
        0x20, 0x4E, 0x01, 0x00, 0x01, 0x00,
        0x7A, 0x12
    };
    gpsSerial.write(updateRate5Hz, sizeof(updateRate5Hz));
    Serial.println("[GPS] Da cau hinh 5Hz cho NEO-6M");
}

// ══════════════════════════════════════════════════════════
//  TÍNH VẬN TỐC SMOOTH (Low-pass filter từ file vantoc)
// ══════════════════════════════════════════════════════════

float calcSmoothedSpeed(float rawSpeed) {
    if (rawSpeed < SPEED_ZERO) {
        // Đứng yên hoặc rung nhiễu → ép về 0
        smoothSpeed = 0.0f;
    } else {
        // Low-pass filter: trung bình có trọng số giữa giá trị mới và cũ
        // alpha=0.2 → mượt mà, phản hồi tốt, không bị trễ quá nhiều
        smoothSpeed = (ALPHA * rawSpeed) + ((1.0f - ALPHA) * smoothSpeed);
    }
    return smoothSpeed;
}

// ══════════════════════════════════════════════════════════
//  GỬI HTTP POST LÊN FLASK
// ══════════════════════════════════════════════════════════

bool httpPost(float lat, float lng, float speed, bool fallen, bool theft) {
    String body = "{\"user_id\":"     + String(user_id)
                + ",\"lat\":"         + String(lat, 6)
                + ",\"lng\":"         + String(lng, 6)
                + ",\"speed\":"       + String(speed, 1)
                + ",\"is_fallen\":"   + (fallen ? "true" : "false")
                + ",\"theft_alert\":" + (theft  ? "true" : "false")
                + "}";

    Serial.println("[HTTP] POST -> " + body);

    sendAT("AT+HTTPTERM", 800);
    delay(300);

    String r = sendAT("AT+HTTPINIT", 2000);
    if (r.indexOf("OK") < 0) {
        Serial.println("[HTTP] HTTPINIT fail!");
        return false;
    }

    String url = "http://" + LOCALTUNNEL_HOST + API_PATH;
    sendAT("AT+HTTPPARA=\"URL\",\"" + url + "\"", 1000);
    sendAT("AT+HTTPPARA=\"CONTENT\",\"application/json\"", 1000);
    sendAT("AT+HTTPPARA=\"USERDATA\",\"bypass-tunnel-reminder: true\\r\\n\"", 1000);

    String dataCmd = "AT+HTTPDATA=" + String(body.length()) + ",5000";
    String dr = sendAT(dataCmd, 2000);
    if (dr.indexOf("DOWNLOAD") < 0) {
        Serial.println("[HTTP] DOWNLOAD mode fail!");
        sendAT("AT+HTTPTERM", 800);
        return false;
    }

    Serial2.print(body);
    delay(1500);

    String result = sendAT("AT+HTTPACTION=1", 8000);
    bool ok = result.indexOf("+HTTPACTION: 1,200") >= 0;

    if (ok) {
        sendAT("AT+HTTPREAD", 2000);
        Serial.println("[HTTP] THANH CONG!");
    } else {
        Serial.println("[HTTP] That bai! Code: " + result);
    }

    sendAT("AT+HTTPTERM", 800);
    return ok;
}

// ══════════════════════════════════════════════════════════
//  SETUP
// ══════════════════════════════════════════════════════════

void setup() {
    pinMode(LED1,   OUTPUT);
    pinMode(LED2,   OUTPUT);
    pinMode(BUZZER, OUTPUT);
    digitalWrite(BUZZER, LOW);
    digitalWrite(LED1,   LOW);
    digitalWrite(LED2,   LOW);

    Serial.begin(115200);
    delay(500);
    Serial.println("\n==============================");
    Serial.println("   SMART MOTO - FINAL");
    Serial.println("==============================");

    // GPS — khởi động rồi cấu hình 5Hz
    gpsSerial.begin(9600, SERIAL_8N1, 4, 2);
    delay(1000);
    setGPS5Hz();   // ← Tăng tần số cập nhật, vận tốc mượt hơn
    Serial.println("[GPS] NEO-6M OK (RX=4, TX=2) - 5Hz mode");

    // MPU6050
    Wire.begin(21, 15);
    if (!mpu.begin()) {
        Serial.println("[MPU] Khong tim thay MPU6050!");
        while (1) delay(10);
    }
    mpu.setAccelerometerRange(MPU6050_RANGE_8_G);
    mpu.setGyroRange(MPU6050_RANGE_500_DEG);
    mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);
    Serial.println("[MPU] MPU6050 OK!");

    // SIM A7682S
    Serial2.begin(115200, SERIAL_8N1, 17, 16);
    delay(1000);
    sendAT("AT", 1000);
    sendAT("AT+CPIN?", 1000);
    sendAT("AT+HTTPTERM", 500);
    sendAT("AT+CSSLCFG=\"sslversion\",1,0", 1000);
    Serial.println("[SIM] A7682S OK!");

    Serial.println("==============================");
    Serial.println("   SAN SANG! Cho GPS fix...");
    Serial.println("==============================\n");
}

// ══════════════════════════════════════════════════════════
//  LOOP
// ══════════════════════════════════════════════════════════

void loop() {
    // ── Đọc GPS liên tục ──
    while (gpsSerial.available() > 0) {
        gps.encode(gpsSerial.read());
    }

    // ── Đọc MPU6050 ──
    sensors_event_t a, g, temp;
    mpu.getEvent(&a, &g, &temp);

    float vibration = abs(a.acceleration.x)
                    + abs(a.acceleration.y)
                    + abs(a.acceleration.z - 9.8);

    bool is_fallen = (abs(a.acceleration.x) > FALL_THRESHOLD ||
                      abs(a.acceleration.y) > FALL_THRESHOLD);

    // ── LOGIC CHỐNG TRỘM ──
    if (vibration > THEFT_THRESHOLD && !is_fallen) {
        is_theft = true;
        Serial.printf("[ALARM] BAO DONG TROM! Do rung: %.2f\n", vibration);

        // Còi bật ngay lập tức, liên tục
        digitalWrite(BUZZER, HIGH);
        digitalWrite(LED1, HIGH);
        digitalWrite(LED2, LOW);

        // SMS + gọi điện cooldown 30 giây
        if (millis() - lastAlarmTime > ALARM_COOLDOWN) {
            lastAlarmTime = millis();
            sendSMS(PHONE_NUMBER, "CANH BAO: Xe cua ban dang bi tac dong manh!");
            makeCall(PHONE_NUMBER);
        }

    } else if (is_fallen) {
        is_theft = false;
        int s = (millis() % 300 < 150) ? HIGH : LOW;
        digitalWrite(BUZZER, s);
        digitalWrite(LED1, s);
        digitalWrite(LED2, s);

        if (millis() - lastAlarmTime > ALARM_COOLDOWN) {
            lastAlarmTime = millis();
            sendSMS(PHONE_NUMBER, "CANH BAO: Xe co the bi nga! Kiem tra ngay.");
            makeCall(PHONE_NUMBER);
        }

    } else {
        // Bình thường: tắt còi ngay
        is_theft = false;
        digitalWrite(BUZZER, LOW);

        if (!gps.location.isValid()) {
            // Chờ GPS: LED chạy tuần tự
            if (millis() - prevLEDMillis >= 150) {
                prevLEDMillis = millis();
                ledStep = (ledStep + 1) % 3;
                digitalWrite(LED1, ledStep == 0 ? HIGH : LOW);
                digitalWrite(LED2, ledStep == 1 ? HIGH : LOW);
            }
        } else {
            // GPS OK: LED sáng đứng
            digitalWrite(LED1, HIGH);
            digitalWrite(LED2, HIGH);
        }
    }

    // ── Gửi HTTP mỗi 5 giây ──
    if (millis() - lastHttpTime >= HTTP_INTERVAL) {
        lastHttpTime = millis();

        if (!gps.location.isValid()) {
            Serial.printf("[GPS] Chua fix | Sats: %d | Chars: %lu\n",
                gps.satellites.value(), gps.charsProcessed());
        } else {
            float lat      = gps.location.lat();
            float lng      = gps.location.lng();
            float rawSpeed = gps.speed.kmph();

            // Áp dụng Low-pass filter (từ file vantoc)
            float speed = calcSmoothedSpeed(rawSpeed);

            Serial.printf("[GPS] Lat: %.6f | Lng: %.6f | Raw: %.1f | Smooth: %.1f km/h | Sats: %d\n",
                lat, lng, rawSpeed, speed, gps.satellites.value());

            httpPost(lat, lng, speed, is_fallen, is_theft);
        }
    }

    delay(200);
}
