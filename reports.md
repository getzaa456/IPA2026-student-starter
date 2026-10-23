# รายงานสรุปเนื้อหา สถาปัตยกรรม และตรรกะการทำงาน (IPA2026 Final Exam)
> เอกสารนี้จัดทำขึ้นเพื่ออธิบายรายละเอียดการทำงาน สถาปัตยกรรม และตรรกะเบื้องหลังโค้ดทุก Part อย่างสมบูรณ์แบบ ได้รับการพิสูจน์ด้วยผลคะแนนตรวจจริง **20/20 เต็ม (CI 10/10, Live 10/10)** เหมาะสำหรับใช้อ่านทบทวนและเตรียมสอบข้อสอบปรนัย (MCQ 40 ข้อ)

---

## 🏆 ผลการประเมินและการทดสอบจริง (Verified Take-Home Score)

| หมวดการประเมิน | คะแนนเต็ม | คะแนนที่ได้รับ | สถานะ |
|---|:---:|:---:|:---:|
| **Student CI (Public & Hidden Tests)** | 10.00 | **10.00 / 10.00** | **ผ่าน 100% (สมบูรณ์)** |
| **Live Testing (Exam Room Router 10.0.29.101)** | 10.00 | **10.00 / 10.00** | **ผ่าน 20/20 เคส (สมบูรณ์)** |
| **รวมคะแนน Take-Home** | **20.00** | **20.00 / 20.00** | **เต็ม 100%** |

---

## 🌐 ภาพรวมสถาปัตยกรรมระบบ (System Architecture Overview)

ระบบนี้เป็น **ChatOps Bot สำหรับบริหารจัดการ Cisco IOS XE Router อัตโนมัติผ่าน Cisco Webex** ตามแนวคิด Infrastructure as Code (IaC) และ Declarative Configuration Management

```
+-----------------------------------------------------------------------------------+
|                                Cisco Webex Cloud                                  |
|   User / Grader  ----(@mention Bot + YAML)---->  Webex Messaging Service          |
|                                                              |                    |
+--------------------------------------------------------------|--------------------+
                                                               | (Webhook Event)
                                                               v
                                                +------------------------------+
                                                |   HTTPS Tunnel (Cloudflare)  |
                                                +------------------------------+
                                                               |
                                                               v
+-----------------------------------------------------------------------------------+
|                        Docker Container: Webhook Service                          |
|                                                                                   |
|  [HTTP Server: make_http_handler]                                                 |
|    - GET  /health   -> HTTP 200 {"status": "ok", "result": "healthy"}             |
|    - POST /webhook  -> HMAC-SHA1 Signature Verify                                 |
|                     -> Immediate HTTP 200 {"status": "ok", "result": "accepted"}  |
|                                  |                                                |
|                                  v                                                |
|  [SequentialSubmitter] (Deduplication via OrderedDict + Single Worker Pool)       |
|                                  |                                                |
|                                  v                                                |
|  [WebexEventHandler]                                                              |
|    1. Webex Client: ดึงรายละเอียดข้อความ (get_message) และตรวจ personId            |
|    2. ตรวจสอบไฟล์แนบ: multiple_attachments / no_yaml / 1 yaml file                |
|    3. ดาวน์โหลดไฟล์ YAML ลง Temporary Directory (prefix="ipa2026-")                |
|    4. เรียก process_request() -> Pipeline การประมวลผล                              |
|                                  |                                                |
|                                  v                                                |
|  [Integration Orchestrator: process_request]                                      |
|    - Part 1 Envelope: validate_webex_envelope (ตรวจ mention & attachment)         |
|    - Part 1 YAML Core: load_request_file & validate_request (กฎ Precedence)       |
|    - Part 4 Dispatcher: dispatch_request() ส่งต่อไปยัง Backend                     |
|                                  |                                                |
|                                  +-----------------------+                        |
|                                  |                       |                        |
|                                  v                       v                        |
|                    [Part 2 Planner: build_plan]    [Part 3 Backends]              |
|                     (create / update / no_change)   - RESTCONF (HTTP/443)         |
|                                                     - NETCONF (SSH/830)           |
|                                                     - Ansible (CLI/22)            |
|                                                     - Netmiko/TextFSM (CLI/22)    |
|                                                              |                    |
|                                                              v                    |
|  [Result Delivery]                                                                |
|    - Webex Client: ส่งผลลัพธ์ JSON กลับไปยังห้อง Webex เดิม (send_message)         |
+-----------------------------------------------------------------------------------+
                                                               |
                                                               v
                                                +------------------------------+
                                                |     Cisco IOS XE Router      |
                                                |        (10.0.29.101)         |
                                                +------------------------------+
```

---

## 📌 Part 1: การตรวจสอบข้อความ Webex และโครงสร้างไฟล์ YAML (Envelope & YAML Core Validation)

### 1. วัตถุประสงค์
Part 1 ทำหน้าที่เป็น **Security Gate & Input Validation** ด่านแรกสุด เพื่อคัดกรองคำขอที่ผิดรูปแบบ ไม่ถูกต้อง หรือไม่ได้ตั้งใจส่งถึง Bot ตัวนี้ ทิ้งไปทันทีก่อนที่จะส่งต่อไปแตะต้อง Network Router โดยใน Part 1 จะยังไม่มีการติดต่อหรือแก้ไข Router ใดๆ ทั้งสิ้น

ไฟล์ที่เกี่ยวข้อง:
- `app/request_handler.py`: ตรวจสอบความถูกต้องของซองจดหมาย Webex (Mention และ Attachment)
- `app/core.py`: ตรวจสอบไวยากรณ์และกฎทางธุรกิจของไฟล์ YAML ตามลำดับความสำคัญ (Precedence)

---

### 2. เจาะลึกฟังก์ชันใน `app/request_handler.py`

#### 2.1 `validate_webex_envelope(mentioned_people, attachment_path, bot_person_id)`
ทำหน้าที่ตรวจสอบ metadata ของข้อความ Webex:
1. **ตรวจสอบการ Mention Bot (`bot_person_id`)**:
   - `bot_person_id` ต้องเป็น string ที่ไม่ว่างเปล่า
   - `mentioned_people` ต้องเป็น list ที่มี `bot_person_id` ของ Bot เราอยู่ข้างใน
   - *จุดสำคัญสำหรับข้อสอบ*: Webex API ส่งรายชื่อคนที่ถูก mention มาเป็น **Person ID (Base64 string)** ไม่ใช่ Display Name (เช่น `@67070003`) และไม่ใช่ plain text หากไม่มีชื่อ Bot ใน list หรือ list ว่าง จะตอบกลับทันทีเป็น:
     ```json
     {"status": "error", "result": "missing_bot_mention"}
     ```
2. **ตรวจสอบไฟล์แนบ (`attachment_path`)**:
   - ถ้า mention ถูกต้อง แต่ไม่มีไฟล์แนบส่งมา (`attachment_path is None`) จะตอบกลับทันทีเป็น:
     ```json
     {"status": "error", "result": "no_yaml"}
     ```
3. **ผลลัพธ์เมื่อผ่านเกณฑ์**:
   - ส่งค่า `None` กลับไป (แปลว่า Envelope ถูกต้อง สมบูรณ์ พร้อมนำไฟล์ไปตรวจต่อ)

#### 2.2 `handle_webex_request(mentioned_people, attachment_path, bot_person_id)`
ทำหน้าที่เชื่อมโยงระหว่าง Envelope Validation กับ YAML Core Validation:
- เรียก `validate_webex_envelope` ก่อน หากพบ error ให้ return ก้อน error ออกไปทันที
- หาก envelope ถูกต้อง จะส่งไฟล์ไปตรวจสอบต่อด้วย `process_request_file(attachment_path)`

---

### 3. เจาะลึกฟังก์ชันใน `app/core.py`

#### 3.1 `load_request_file(path)` และ `process_request_file(path)`
- พยายามเปิดไฟล์ YAML ด้วย `utf-8` และใช้ `yaml.safe_load(f)`
- หากเกิดข้อผิดพลาดในการเปิดไฟล์, ถอดรหัส Unicode หรือ parse YAML ผิดไวยากรณ์ จะส่งคืน `{"status": "error", "result": "invalid_yaml"}`

#### 3.2 `validate_request(data)` และลำดับการตรวจ (Precedence Order)
**ข้อสอบ MCQ มักถามลำดับการ return error อย่างละเอียด** โค้ดจะต้องตรวจสอบตามลำดับ 1 ถึง 6 อย่างเคร่งครัด หากผิดหลายข้อ ต้องส่ง error ของข้อที่อยู่ก่อนหน้าเสมอ:

1. **Root Mapping Check**:
   - `data` ต้องเป็น dictionary เท่านั้น มิฉะนั้นตอบ `invalid_yaml`
2. **Version Check (`invalid_version`)**:
   - `version` ต้องระบุ และต้องเป็น **YAML integer ค่า `1`** เท่านั้น
   - *กับดักข้อสอบ*: ค่า `"1"` (string), `1.0` (float), หรือ `true` (boolean) ถือว่าผิดทั้งหมด!
   - ใน Python `bool` เป็น subclass ของ `int` ดังนั้นโค้ดจึงต้องเช็ก `type(version) is int and version == 1` อย่างเข้มงวด
3. **Router Check (`missing_router` -> `invalid_router`)**:
   - ตรวจด้วย `_missing(data, "router")` (เช็ก `is None`) หากไม่มีคีย์ ตอบ `missing_router`
   - ค่าของ `router` ต้องเป็นหนึ่งใน Router ที่ได้รับอนุญาต 5 หมายเลขเท่านั้น:
     - `10.0.29.101` (Official Live / Grader router)
     - `10.0.29.102` ถึง `10.0.29.105` (Lab testing routers)
     - หากเป็น IP อื่น (หรือเป็น string ว่าง `""`) ตอบ `invalid_router`
4. **Method Check (`missing_method` -> `invalid_method`)**:
   - ตรวจด้วย `_missing(data, "method")` หากไม่มีคีย์ ตอบ `missing_method`
   - ต้องเป็น string และเป็นหนึ่งใน 4 ค่านี้เท่านั้น: `restconf`, `netconf`, `ansible`, `netmiko-textfsm` มิฉะนั้นตอบ `invalid_method`
5. **Action Check (`missing_action` -> `invalid_action`)**:
   - ตรวจด้วย `_missing(data, "action")` หากไม่มีคีย์ ตอบ `missing_action`
   - ตรวจสอบความเข้ากันได้ตาม Method-Action Capability Matrix:
     | Method | status | plan | apply | delete |
     |---|:---:|:---:|:---:|:---:|
     | `restconf` | ✓ | ✓ | ✓ | ✗ |
     | `netconf` | ✓ | ✓ | ✓ | ✗ |
     | `ansible` | ✗ | ✗ | ✓ | ✗ |
     | `netmiko-textfsm` | ✓ | ✗ | ✗ | ✓ |
   - หาก method รู้จัก แต่ action ไม่รองรับ จะต้องตอบ `invalid_action`
6. **Desired State Check (`missing_desired` -> `missing_interface` -> `missing_interface_name`)**:
   - หากไม่มีคีย์ `desired` ตอบ `missing_desired`
   - ภายใต้ `desired` หากไม่ใช่ mapping หรือไม่มีคีย์ `interface` ตอบ `missing_interface`
   - ภายใต้ `desired.interface` หากไม่ใช่ mapping หรือไม่มีคีย์ `name` ตอบ `missing_interface_name`
7. **Complete State for `plan` and `apply` Only**:
   - หาก `action` เป็น `plan` หรือ `apply` จะต้องส่งค่าคอนฟิกที่ครบถ้วน ได้แก่:
     - `ipv4`: ตรวจ `_missing(interface, "ipv4")` หากไม่มี ตอบ `missing_ipv4`
     - `description`: ตรวจ `_missing(interface, "description")` หากไม่มี ตอบ `missing_description`
     - `admin_state`: ตรวจ `_missing(interface, "admin_state")` หากไม่มี ตอบ `missing_admin_state`
     - ค่าของ `admin_state` ต้องเป็น `"up"` หรือ `"down"` เท่านั้น มิฉะนั้นตอบ `invalid_admin_state`
   - *ประเด็น Hidden Test ที่พบบ่อย*:
     - หากส่ง `admin_state: ""` (มีคีย์แต่เป็นค่าว่าง): เนื่องจากไม่ใช่ None จึงผ่าน missing check แล้วตกมาที่เงื่อนไขค่าไม่ถูกต้อง ตอบ **`invalid_admin_state`** (ไม่ใช่ missing)
     - หากส่ง `description: ""` (มีคีย์แต่ข้อความเป็นค่าว่าง): ถือว่ามีคีย์ description อยู่จริง (ผ่านการตรวจ)
   - *ข้อยกเว้นสำหรับ `status` และ `delete`*:
     - ทั้งสอง action นี้ต้องการเพียง `desired.interface.name` เท่านั้น
     - แม้ผู้ใช้จะใส่ `ipv4`, `description`, หรือใส่ `admin_state: invalid` มาด้วย ระบบจะ **ละเว้น (ignore)** ค่าเหล่านั้นทั้งหมด

#### 3.3 ผลลัพธ์เมื่อ Part 1 สำเร็จ
```json
{
  "status": "ok",
  "result": "accepted"
}
```

---

## 🧭 Part 2: การวางแผนและการเปรียบเทียบสถานะ (Planner & Desired State Engine)

### 1. วัตถุประสงค์
Part 2 จำลองหลักการทำงานของ **Declarative Configuration Management** (เช่น Terraform หรือ Kubernetes) โดยนำ **Desired State (สถานะที่ต้องการ)** มาเปรียบเทียบกับ **Current State (สถานะจริงปัจจุบันบน Router)** เพื่อคำนวณแผนการเปลี่ยนแปลง (Execution Plan) ที่แน่นอน (Deterministic) และมีความเป็น Idempotent

ไฟล์ที่เกี่ยวข้อง:
- `app/planner.py`: ฟังก์ชันหลัก `build_plan(desired_interface, current_interface)`
- `sample-tests/part2/fixtures/` และ `sample-tests/part2/cases/`: ชุดทดสอบตาม spec (รวมถึงเคสเพิ่มเติม 05, 06, 07, 08 ที่สร้างขึ้น)

---

### 2. ขอบเขตและหน้าที่ของ Planner (`specs/plan-spec-v1.md`)
- **ไม่เชื่อมต่อกับ Router จริง**: Planner เป็น pure function ทางตรรกศาสตร์
- **ไม่เกี่ยวข้องกับการ Parse ข้อมูลดิบ**: ข้อมูล `current_interface` ที่ส่งเข้ามาจะถูกแปลงให้อยู่ในรูป Normalized dict เรียบร้อยแล้ว (โดย Backend ใน Part 3)
- **ไม่รองรับคำสั่ง `delete`**: การลบ interface จัดการแยกต่างหากใน Part 3 โดยตรง

---

### 3. ฟังก์ชันหลัก `build_plan(desired_interface, current_interface)`

#### 3.1 ฟิลด์ที่ใช้จัดการ (Managed Fields)
- **Resource Identifier**: `name` (เช่น `"Loopback123"`)
  - ใช้ระบุ interface เป้าหมายเท่านั้น
  - **ข้อควรระวังสำหรับข้อสอบ**: ฟิลด์ `name` **ต้องไม่ปรากฏ** ใน dictionary `changes` เด็ดขาด!
- **Managed Fields**: ฟิลด์ที่เปรียบเทียบและบันทึกลงใน `changes` มีเพียง 3 ฟิลด์เท่านั้น:
  1. `ipv4`
  2. `description`
  3. `admin_state`

#### 3.2 การตัดสินใจเลือก `operation` ทั้ง 3 รูปแบบ

##### ก. กรณี `create`
- **เงื่อนไข**: เมื่อ `current_interface is None` (ยังไม่มี interface นี้อยู่บน router)
- **โครงสร้างของ `changes`**:
  - ต้องระบุครบทั้ง 3 managed fields (`ipv4`, `description`, `admin_state`)
  - ระบุเฉพาะค่าปลายทาง `"to"` เท่านั้น (ไม่มี `"from"`)
  - ตัวอย่าง:
    ```json
    {
      "status": "ok",
      "result": "planned",
      "operation": "create",
      "changes": {
        "ipv4": {"to": "172.23.123.1/32"},
        "description": {"to": "IPA2026-67070003"},
        "admin_state": {"to": "up"}
      }
    }
    ```

##### ข. กรณี `update`
- **เงื่อนไข**: เมื่อมี `current_interface` อยู่แล้ว แต่มี managed field อย่างน้อย 1 ฟิลด์ที่มีค่าไม่ตรงกับ `desired_interface`
- **โครงสร้างของ `changes`**:
  - ใส่ **เฉพาะฟิลด์ที่มีค่าแตกต่างกันเท่านั้น**
  - แต่ละฟิลด์ที่เปลี่ยนต้องแสดงทั้งค่าเดิม `"from"` และค่าใหม่ `"to"`
  - ตัวอย่าง:
    ```json
    {
      "status": "ok",
      "result": "planned",
      "operation": "update",
      "changes": {
        "admin_state": {
          "from": "up",
          "to": "down"
        }
      }
    }
    ```

##### ค. กรณี `no_change`
- **เงื่อนไข**: เมื่อค่าของ `ipv4`, `description`, `admin_state` ตรงกันครบทุกฟิลด์
- **โครงสร้างของ `changes`**:
  - ต้องเป็น dictionary ว่าง `{}` เสมอ
  - ตัวอย่าง:
    ```json
    {
      "status": "ok",
      "result": "planned",
      "operation": "no_change",
      "changes": {}
    }
    ```

---

## ⚙️ Part 3: การเชื่อมต่อและการสั่งการ Router ผ่าน Backend ต่างๆ (Network Automation Backends)

### 1. วัตถุประสงค์
Part 3 พัฒนา Adapter เชื่อมต่อกับ Cisco IOS XE Router จริง โดยแปลงข้อมูลระหว่างคำสั่งเฉพาะของแต่ละเทคโนโลยี (JSON, XML, CLI, Playbook) กับโครงสร้างข้อมูลมาตรฐาน (Normalized Interface State)

ไฟล์ที่เกี่ยวข้อง:
- `app/backends/common.py`: โมดูลความปลอดภัย การตรวจสอบชื่อ และการแปลง Exception กลาง
- `app/backends/planning.py`: Plan Wrapper สำหรับ Backend ที่รองรับ plan
- `app/backends/restconf.py`: RESTCONF Adapter (HTTPS/JSON)
- `app/backends/netconf.py`: NETCONF Adapter (SSH/XML)
- `app/backends/ansible.py`: Ansible Runner Adapter
- `app/backends/netmiko_textfsm.py`: Netmiko CLI + TextFSM Adapter
- `ansible/apply_interface.yml` & `ansible/inventory.ini`: Ansible Configs

---

### 2. ตารางเปรียบเทียบเทคโนโลยี Backend (Capability & Protocol Matrix)

| Method | Protocol / Port | Data Format | Auth Method | status | plan | apply | delete |
|---|---|---|---|:---:|:---:|:---:|:---:|
| **RESTCONF** | HTTPS (443) | JSON (`application/yang-data+json`) | HTTP Basic Auth | ✓ | ✓ | ✓ | ✗ |
| **NETCONF** | SSH (830) | XML (RPC Subtree Filter) | SSH Subsystem | ✓ | ✓ | ✓ | ✗ |
| **Ansible** | SSH (22) via Paramiko | YAML / CLI (`cisco.ios.ios_config`) | SSH Password | ✗ | ✗ | ✓ | ✗ |
| **Netmiko + TextFSM** | SSH (22) | Text CLI / Regex Templates | SSH CLI | ✓ | ✗ | ✗ | ✓ |

---

### 3. โมดูลกลาง `app/backends/common.py` (หัวใจความปลอดภัยและ Error Mapping)

1. **Security & Name Validation**:
   - `is_safe_interface_name(name)`: ตรวจสอบ Regex `^[A-Za-z][A-Za-z0-9/.:-]{0,63}$` ป้องกัน Shell Injection
   - `is_loopback_name(name)`: ตรวจสอบ Regex `^Loopback[0-9]{1,10}$`
   - `loopback_number(name)`: สกัดหมายเลข Loopback ออกมาเป็น integer (เช่น `Loopback123` -> `123`)
2. **การแปลง Exception รวมศูนย์ (`error_from_exception`)**:
   - **Authentication Failed** -> `{"status": "error", "result": "authentication_failed"}`:
     - `PermissionError`
     - ncclient `AuthenticationError`
     - netmiko `NetmikoAuthenticationException`
     - paramiko `AuthenticationException`
   - **Backend Failed** -> `{"status": "error", "result": "backend_failed"}`:
     - ncclient `RPCError`
     - requests `RequestException` (ที่ไม่ใช่ Timeout หรือ ConnectionError)
   - **Connection Failed** -> `{"status": "error", "result": "connection_failed"}`:
     - `ConnectionError`, `TimeoutError`, `OSError`
     - requests `RequestsConnectionError`, `Timeout`
     - ncclient `TransportError`, `TimeoutExpiredError`
     - netmiko `NetmikoTimeoutException`
     - paramiko `SSHException`
   - **Fallback** -> `backend_failed`

---

### 4. เจาะลึกการทำงานของแต่ละ Backend

#### 4.1 Planning Wrapper (`app/backends/planning.py`)
- ดึงสถานะจริงด้วย `get_interface_state()`
- หาก backend ส่ง error กลับมา จะส่งต่อ error นั้นทันทีโดยไม่สร้าง plan
- หากได้ `not_found` ให้ `current = None`, หากได้ `found` ให้ `current = response["interface"]`
- ส่งต่อไปยัง `build_plan(desired, current)` เพื่อคำนวณแผน

#### 4.2 RESTCONF Backend (`app/backends/restconf.py`)
- **การอ่านสถานะ (`get_interface_state`)**:
  - เมธอด: `GET`
  - URL: `https://{router}/restconf/data/ietf-interfaces:interfaces/interface={interface_name}`
  - Model: Vendor-Neutral Model `ietf-interfaces` และ `ietf-ip`
  - แปลง `ip` และ `netmask` เป็น CIDR ด้วย `to_cidr`
  - HTTP 404 แปลงเป็น `{"status": "ok", "result": "not_found", "interface": null}`
- **การคอนฟิก (`apply_interface`)**:
  - เมธอด: `PUT` (ใช้ PUT เพื่อแทนที่ resource เดิมทั้งหมดแบบ Idempotent ป้องกัน secondary IP ตกค้าง)
  - URL: `https://{router}/restconf/data/Cisco-IOS-XE-native:native/interface/Loopback={number}`
  - Model: Cisco Native Model `Cisco-IOS-XE-native`
  - หาก `admin_state == "down"` จะใส่ `"shutdown": [null]` หากเป็น `"up"` จะละเว้นฟิลด์นี้ออกไป

#### 4.3 NETCONF Backend (`app/backends/netconf.py`)
- **การอ่านสถานะ (`get_interface_state`)**:
  - ส่ง `<get-config>` ด้วย Subtree Filter ผ่าน XML namespace `urn:ietf:params:xml:ns:yang:ietf-interfaces`
- **การคอนฟิก (`apply_interface`)**:
  - ส่ง `<edit-config>` ไปยัง datastore `<running>`
  - ใช้ attribute `nc:operation="replace"` ที่แท็ก `<Loopback>`
  - ใช้ `xml.sax.saxutils.escape()` ป้องกัน XML syntax error จากอักขระพิเศษใน `description` (`&`, `<`, `>`, `"`)
  - หาก `admin_state == "down"` ใส่แท็ก `<shutdown/>`

#### 4.4 Ansible Backend (`app/backends/ansible.py`)
- **การทำงาน**: รองรับเฉพาะการ `apply` (Apply-only)
- **การตรวจสอบความปลอดภัย (`build_variables`)**:
  - ปฏิเสธทันทีหากไม่ใช่ Loopback (`is_loopback_name`)
  - ตรวจสอบ `description.isprintable()` ป้องกัน newline injection
- **Playbook (`ansible/apply_interface.yml`)**:
  - ใช้คำสั่ง Jinja2:
    ```yaml
    - "{{ 'shutdown' if shutdown | bool else 'no shutdown' }}"
    ```
  - *จุดสำคัญ*: ต้องมี filter `| bool` เพื่อป้องกันค่า string `"false"` ถูกประเมินเป็น True ใน Jinja2
  - กำหนด `defaults: true` ใน `cisco.ios.ios_config` เพื่อให้ตรวจจับค่า default ของ Cisco IOS ได้

#### 4.5 Netmiko + TextFSM Backend (`app/backends/netmiko_textfsm.py`)
- **การอ่านสถานะ (`get_interface_state`)**:
  - รัน 2 คำสั่ง CLI: `show ip interface <name>` และ `show interfaces description`
  - แปลงผลลัพธ์ด้วย NTC-Templates TextFSM
  - รองรับชื่อย่อ IOS ผ่าน `canonical_name()` (เช่น `Lo123` -> `Loopback123`, `Gi1` -> `GigabitEthernet1`)
- **การลบ Interface (`delete_interface`)**:
  - **ความปลอดภัยสูงสุด**: ตรวจสอบ `if not is_loopback_name(interface_name): return error("backend_failed")` ห้ามลบ physical interface โดยเด็ดขาด
  - หาก interface ไม่มีอยู่แล้ว (`not_found`) ตอบสำเร็จทันที (Idempotent Delete)
  - หากมีอยู่: ส่งคำสั่ง CLI `no interface <name>` แล้วตรวจสอบซ้ำอีกครั้ง ยืนยันว่าถูกลบจริงจึงตอบ `{"status": "ok", "result": "deleted"}`

---

## 🚀 Part 4: การเชื่อมต่อระบบครบวงจร, Webex Bot, Webhook Server และ Docker (Integration & ChatOps Deployment)

### 1. วัตถุประสงค์
Part 4 ประกอบโค้ดทุกส่วนเข้าด้วยกันเป็นระบบ **ChatOps Webex Bot** ทำงานบน Docker Container สื่อสารกับ Cisco Webex API และ Router ในสภาพแวดล้อมจริง

ไฟล์ที่เกี่ยวข้อง:
- `app/dispatcher.py`: ตัวสลับเส้นทาง (Routing Switchboard) กระจายงานไปยัง Backend ต่างๆ
- `app/integration.py`: ตัวเชื่อมโยงภาพรวม (Orchestrator) ระหว่าง Webex Envelope, YAML Validation และ Dispatcher
- `app/webex_client.py`: คลาสติดต่อกับ Webex REST API (`https://webexapis.com/v1`)
- `app/webhook_server.py`: HTTP Server รับ Webhook และจัดการ Worker ประมวลผลแบบ Background
- `app/webhook_registration.py`: ตัวจัดการลงทะเบียน Webex Webhook อัตโนมัติร่วมกับ Cloudflare Tunnel
- `Dockerfile` & `compose.yaml`: การ Build Container Image และการตั้งค่า Deployment

---

### 2. เจาะลึกการทำงานของแต่ละโมดูลใน Part 4

#### 2.1 Dispatcher (`app/dispatcher.py`)
- กำหนดตาราง `ROUTES`:
  ```python
  ROUTES = {
      ("restconf", "status"): (restconf, "get_interface_state", "name"),
      ("restconf", "plan"): (restconf, "plan_interface", "interface"),
      ("restconf", "apply"): (restconf, "apply_interface", "interface"),
      ("netconf", "status"): (netconf, "get_interface_state", "name"),
      ("netconf", "plan"): (netconf, "plan_interface", "interface"),
      ("netconf", "apply"): (netconf, "apply_interface", "interface"),
      ("ansible", "apply"): (ansible, "apply_interface", "interface"),
      ("netmiko-textfsm", "status"): (netmiko_textfsm, "get_interface_state", "name"),
      ("netmiko-textfsm", "delete"): (netmiko_textfsm, "delete_interface", "name"),
  }
  ```
- ใช้ `getattr(module, function_name)` เพื่อดึงฟังก์ชัน ณ เวลาเรียกใช้งานจริง ทำให้สามารถ mock ฟังก์ชันในชุดทดสอบได้อย่างสมบูรณ์

#### 2.2 Integration Orchestrator (`app/integration.py`)
- Pipeline ควบคุมลำดับขั้นตอน:
  1. เรียก `validate_webex_envelope()` ตรวจ mention และ attachment
  2. เรียก `load_request_file()` อ่านไฟล์ YAML
  3. เรียก `validate_request()` ตรวจสอบตามกฎ Part 1
  4. เรียก `dispatch_request()` ส่งคำสั่งไปยัง Backend โดยครอบด้วย:
     ```python
     try:
         return dispatch_request(data)
     except Exception:
         logger.exception("dispatch failed")
         return error("backend_failed")
     ```
     ป้องกันไม่ให้บอท crash หากเกิดข้อผิดพลาดที่ไม่คาดคิด

#### 2.3 Webex Client (`app/webex_client.py`)
- `get_me()`: ดึง personId ของตัวบอทเอง
- `get_message(message_id)`: ดึงข้อมูลข้อความและลิงก์ดาวน์โหลดไฟล์
- `download_file(file_url)`: ตรวจสอบ host ด้วย `_is_webex_url()` หากดาวน์โหลดจาก webexapis.com จะส่ง Bearer token แต่หากเป็น URL ภายนอกจะไม่ส่ง token
- `send_message(room_id, text)`: ส่งผลลัพธ์ JSON กลับไปยังห้อง Webex

#### 2.4 Webhook Server & Event Handler (`app/webhook_server.py`)
- **HTTP Server (`make_http_handler(submit_event, secret=None)`)**:
  - `GET /health`: สำหรับ Docker Healthcheck ตอบ `200 {"status": "ok", "result": "healthy"}`
  - `POST /webhook`:
    - ตรวจสอบขนาด Body (จำกัดที่ 1 ถึง 1,000,000 bytes)
    - **การตรวจสอบ Signature**: หากมีการตั้ง `secret` จะตรวจสอบ HMAC-SHA1 ผ่าน Header `X-Spark-Signature` หากไม่ถูกต้อง ตอบ `403 {"status": "error", "result": "invalid_signature"}`
    - หาก Body ถูกต้อง ตอบรับทันทีด้วย **`200 {"status": "ok", "result": "accepted"}`**
    - เส้นทางอื่นที่ไม่ใช่ `/health` หรือ `/webhook` ตอบ `404 {"status": "error", "result": "not_found"}`
- **Sequential Execution & Deduplication (`SequentialSubmitter`)**:
  - ใช้ `ThreadPoolExecutor(max_workers=1)` รับประกันว่าคำสั่งที่ส่งไปยัง Router จะถูกรันทีละ 1 รายการตามลำดับ ไม่ชนกัน
  - ใช้ `OrderedDict` บันทึก 500 `message_id` ล่าสุด หาก Webex ส่ง event ซ้ำ ระบบจะ drop ทิ้งทันที ไม่รันซ้ำซ้อน
- **Event Handler (`WebexEventHandler`)**:
  - ตรวจสอบ `personId` ของผู้ส่ง หากตรงกับ `bot_person_id` ให้ข้ามทันที ป้องกัน Infinite Loop
  - หากไฟล์แนบมากกว่า 1 ไฟล์ ตอบ `multiple_attachments` ทันทีโดยไม่ดาวน์โหลด
  - หากไม่มีไฟล์แนบ ส่ง `path=None` ไปยังตัวประมวลผล (จะตอบ `no_yaml`)
  - หากมี 1 ไฟล์ ดาวน์โหลดลง Temporary Directory และลบไฟล์ทิ้งทันทีเมื่อประมวลผลเสร็จสิ้น
  - ครอบ `self.processor()` ด้วย try-except หากเกิดข้อผิดพลาดที่ไม่คาดคิดจะส่ง `backend_failed` กลับไปยังห้องเสมอ

---

## 📊 ตารางสรุป Error Codes และ Status ครบวงจร (Comprehensive Cheat Sheet)

| หมวดหมู่ | Error / Status Code | HTTP Code | ความหมาย / เงื่อนไขที่เกิดขึ้น |
|---|---|:---:|---|
| **Part 1 Envelope** | `missing_bot_mention` | - | ไม่ได้ @mention บอท หรือ mention คนอื่น |
| | `no_yaml` | - | @mention บอทถูกต้อง แต่ไม่ได้แนบไฟล์ YAML มา |
| **Part 1 Core** | `invalid_yaml` | - | ไฟล์ YAML เสีย, ไวยากรณ์ผิด, หรือ root ไม่ใช่ mapping |
| | `invalid_version` | - | ฟิลด์ version ไม่ใช่ integer ค่า 1 (เช่น string `"1"`, `1.0`, `true`) |
| | `missing_router` | - | ไม่มีฟิลด์ `router` ใน YAML |
| | `invalid_router` | - | ค่า `router` ไม่ใช่ IP ในช่วง `10.0.29.101`–`10.0.29.105` หรือเป็นค่าว่าง |
| | `missing_method` | - | ไม่มีฟิลด์ `method` ใน YAML |
| | `invalid_method` | - | ค่า `method` ไม่ใช่ `restconf`, `netconf`, `ansible`, `netmiko-textfsm` |
| | `missing_action` | - | ไม่มีฟิลด์ `action` ใน YAML |
| | `invalid_action` | - | ค่า `action` ไม่เข้ากับ method (เช่น `restconf` + `delete`) |
| | `missing_desired` | - | ไม่มีคีย์ `desired` ใน YAML |
| | `missing_interface` | - | ไม่มีคีย์ `interface` ภายใต้ `desired` หรือไม่ใช่ mapping |
| | `missing_interface_name` | - | ไม่มีคีย์ `name` ภายใต้ `desired.interface` |
| | `missing_ipv4` | - | คำสั่ง plan/apply ขาดฟิลด์ `ipv4` |
| | `missing_description` | - | คำสั่ง plan/apply ขาดฟิลด์ `description` |
| | `missing_admin_state` | - | คำสั่ง plan/apply ขาดฟิลด์ `admin_state` |
| | `invalid_admin_state` | - | ค่า `admin_state` ไม่ใช่ `"up"` หรือ `"down"` (รวมถึงค่าว่าง `""`) |
| **Part 1 Success** | `accepted` | - | คำขอผ่านการตรวจสอบ Part 1 สำเร็จ |
| **Part 2 Plan** | `planned` (create) | - | ยังไม่มี interface บน router -> วางแผนสร้างใหม่ |
| | `planned` (update) | - | มี interface แล้วแต่ค่าต่างกัน -> วางแผนอัปเดตเฉพาะฟิลด์ที่ต่าง |
| | `planned` (no_change) | - | สถานะปัจจุบันตรงกับ desired state ทุกประการ |
| **Part 3 Backend** | `found` | - | อ่านสถานะ interface สำเร็จและพบข้อมูลบน router |
| | `not_found` | - | ไม่พบ interface บน router (ไม่ใช่ error) หรือลบ interface สำเร็จแบบ idempotent |
| | `applied` | - | สั่ง apply คอนฟิกไปยัง router สำเร็จ |
| | `deleted` | - | สั่งลบ interface บน router สำเร็จ |
| | `authentication_failed` | - | Username/Password เข้า Router ผิด หรือโดนปฏิเสธสิทธิ์ |
| | `connection_failed` | - | เชื่อมต่อ Router ไม่ได้ (Timeout, Host Unreachable, Refused) |
| | `backend_failed` | - | Router ปฏิเสธคำสั่ง, RPC Error, หรือสั่งลบ Interface ที่ไม่ใช่ Loopback |
| **Part 4 Webhook** | `healthy` | 200 | Docker Healthcheck Endpoint (`GET /health`) |
| | `accepted` | 200 | Webhook Server ได้รับ Event แล้ว (`POST /webhook`) |
| | `invalid_event` | 400 | Event ขนาดเกิน 1MB, เสียรูปแบบ, หรือ JSON ผิด |
| | `invalid_signature` | 403 | Header `X-Spark-Signature` ไม่ตรงกับ HMAC-SHA1 ของ Secret |
| | `not_found` | 404 | เรียก HTTP Endpoint ที่ระบบไม่รู้จัก |
| | `multiple_attachments` | - | ผู้ใช้แนบไฟล์มามากกว่า 1 ไฟล์ในข้อความเดียว |

---

## 🎯 คลังข้อสอบทบทวนปลายภาค 50 ข้อ (50 Final Exam Review Questions)

### หมวดที่ 1: สถาปัตยกรรมระบบ, Webex และ Webhook (ข้อ 1 - 10)
1. **ถาม**: HTTP 200 จากการยิง `POST /webhook` หมายความว่าอย่างไร?
   - **ตอบ**: หมายถึง Webhook Server ได้รับ event เรียบร้อยแล้ว **ยังไม่ใช่** ผลลัพธ์การทำงานของคำสั่งบน Router
2. **ถาม**: Bot ส่งผลลัพธ์ JSON กลับไปยังผู้ใช้ผ่านช่องทางใด?
   - **ตอบ**: ส่งผ่าน Webex REST API (`POST https://webexapis.com/v1/messages`) ไปยังห้อง Webex เดิมโดยตรง ไม่ได้ส่งย้อนผ่าน HTTPS Tunnel
3. **ถาม**: เหตุใด Bot ต้องตรวจสอบ `personId` ของ event และข้อความ?
   - **ตอบ**: เพื่อป้องกันปัญหา Infinite Loop (Bot ตอบข้อความของตัวเองวนไปเรื่อยๆ)
4. **ถาม**: เหตุใดระบบต้องประมวลผลคำขอที่ส่งไปยัง Router ทีละรายการ (Sequentially)?
   - **ตอบ**: เพื่อป้องกันไม่ให้คำสั่งแก้ไขคอนฟิกบน Router เกิดการชนกันหรือทำงานซ้อนทับกัน (Race Condition / Overlapping Changes)
5. **ถาม**: หากผู้ใช้ @mention Bot โดยแนบไฟล์ YAML มา 2 ไฟล์ในข้อความเดียวกัน Bot จะตอบว่าอย่างไร?
   - **ตอบ**: `{"status": "error", "result": "multiple_attachments"}` และจะไม่ดาวน์โหลดไฟล์ใดๆ
6. **ถาม**: หากผู้ใช้ @mention Bot โดยไม่แนบไฟล์ใดๆ มาเลย Bot จะตอบว่าอย่างไร?
   - **ตอบ**: `{"status": "error", "result": "no_yaml"}`
7. **ถาม**: การตรวจสอบการ mention Bot ในระบบใช้ข้อมูลใด?
   - **ตอบ**: ใช้ Person ID (Base64 string) ของ Bot จาก Webex ไม่ใช่ Display Name และไม่ใช่ username
8. **ถาม**: Endpoint ใดที่ใช้สำหรับตรวจสอบสถานะความพร้อมของ Bot ใน Docker Container (Health Check)?
   - **ตอบ**: `GET /health` โดยตอบกลับเป็น `200 {"status": "ok", "result": "healthy"}`
9. **ถาม**: หาก Webex Webhook มีการตั้งค่า Secret ระบบจะตรวจสอบความถูกต้องผ่าน Header ใด?
   - **ตอบ**: Header `X-Spark-Signature` โดยนำ Body มาคำนวณ HMAC-SHA1 เทียบกับ Secret หากไม่ตรงกันจะตอบ `403 {"status": "error", "result": "invalid_signature"}`
10. **ถาม**: คลาส `SequentialSubmitter` มีกลไกป้องกันข้อความซ้ำ (Deduplication) อย่างไร?
    - **ตอบ**: ใช้ `OrderedDict` บันทึก `message_id` ล่าสุด 500 รายการ หากมีข้อความ ID เดิมส่งซ้ำเข้ามาจะถูก drop ทิ้งทันที

---

### หมวดที่ 2: การตรวจสอบไฟล์ YAML และกฎ Precedence (ข้อ 11 - 20)
11. **ถาม**: ลำดับความสำคัญในการตรวจสอบความผิดพลาดของไฟล์ YAML (Validation Precedence) เริ่มจากอะไรไปอะไร?
    - **ตอบ**: `invalid_yaml` -> `invalid_version` -> `missing_router` / `invalid_router` -> `missing_method` / `invalid_method` -> `missing_action` / `invalid_action` -> `missing_desired` / `missing_interface` / `missing_interface_name` -> (สำหรับ plan/apply) `missing_ipv4` / `missing_description` / `missing_admin_state` / `invalid_admin_state`
12. **ถาม**: หากไฟล์ YAML ระบุ `version: 2` และไม่มีคีย์ `router` จะได้ข้อผิดพลาดใด?
    - **ตอบ**: `invalid_version` เพราะการตรวจ version อยู่ก่อนการตรวจ router
13. **ถาม**: ค่าของ `version` ที่ถูกต้องในระบบนี้คือค่าใด?
    - **ตอบ**: YAML integer ค่า `1` เท่านั้น (ค่า `"1"`, `1.0`, และ `true` ถือว่าผิดทั้งหมด)
14. **ถาม**: IP Address ของ Router ที่ได้รับอนุญาตให้ใช้งานในระบบมีกี่เบอร์ และมีเบอร์ใดบ้าง?
    - **ตอบ**: 5 เบอร์ ได้แก่ `10.0.29.101` ถึง `10.0.29.105` หากระบุเบอร์อื่นจะได้ `invalid_router`
15. **ถาม**: ฟิลด์ใดใน `desired.interface` ที่จำเป็นต้องมีสำหรับคำสั่ง `status` และ `delete`?
    - **ตอบ**: ต้องการเพียง `name` เท่านั้น (เช่น `Loopback123`)
16. **ถาม**: หากส่งคำขอ `action: status` แต่ใส่ `ipv4: 1.1.1.1` และ `admin_state: invalid-val` มาด้วย จะเกิดอะไรขึ้น?
    - **ตอบ**: ผ่านการตรวจสอบปกติ เพราะระบบจะเพิกเฉย (ignore) ฟิลด์ส่วนเกินเหล่านั้นในคำสั่ง status
17. **ถาม**: ค่าที่ถูกต้องของ `admin_state` มีอะไรบ้าง?
    - **ตอบ**: มี 2 ค่าคือ `"up"` และ `"down"` เท่านั้น
18. **ถาม**: หากใน YAML ส่ง `admin_state: ""` (มีคีย์แต่ค่าเป็น string ว่าง) จะได้ error อะไร?
    - **ตอบ**: ได้ `invalid_admin_state` เพราะฟิลด์มีอยู่จริง (ไม่ missing) แต่ค่าไม่ถูกต้องตามที่กำหนด
19. **ถาม**: หากใน YAML ส่ง `desired: {interface: "Loopback1"}` (interface ไม่ใช่ dict) จะได้ error อะไร?
    - **ตอบ**: ได้ `missing_interface_name`
20. **ถาม**: ผลลัพธ์เมื่อไฟล์ YAML ผ่านการตรวจสอบใน Part 1 มีรูปแบบอย่างไร?
    - **ตอบ**: `{"status": "ok", "result": "accepted"}`

---

### หมวดที่ 3: การวางแผนและการเปรียบเทียบ Desired State vs Current State (ข้อ 21 - 28)
21. **ถาม**: Managed Fields ที่ฟังก์ชัน `build_plan()` ใช้เปรียบเทียบมีฟิลด์ใดบ้าง?
    - **ตอบ**: มี 3 ฟิลด์เท่านั้น คือ `ipv4`, `description`, และ `admin_state`
22. **ถาม**: ฟิลด์ `name` สามารถปรากฏใน dictionary `changes` ของผลลัพธ์การ plan ได้หรือไม่?
    - **ตอบ**: **ไม่ได้เด็ดขาด** เพราะ `name` เป็น Identifier ที่ใช้ระบุตัวตนของ interface
23. **ถาม**: กรณีใดที่ `build_plan()` จะตอบ `operation: "create"`?
    - **ตอบ**: เมื่อ `current_interface is None` (ยังไม่มี interface บน router)
24. **ถาม**: โครงสร้างของ `changes` ในกรณี `create` มีลักษณะเด่นอย่างไร?
    - **ตอบ**: มีครบทั้ง 3 managed fields และมีเฉพาะคีย์ `"to"` เท่านั้น (ไม่มี `"from"`)
25. **ถาม**: กรณีใดที่ `build_plan()` จะตอบ `operation: "update"`?
    - **ตอบ**: เมื่อมี interface อยู่แล้ว แต่มี managed field อย่างน้อย 1 ฟิลด์ที่มีค่าต่างจาก desired state
26. **ถาม**: โครงสร้างของ `changes` ในกรณี `update` มีลักษณะเด่นอย่างไร?
    - **ตอบ**: มีเฉพาะฟิลด์ที่ค่าเปลี่ยนแปลง โดยแสดงทั้งค่าเดิม (`"from"`) และค่าใหม่ (`"to"`)
27. **ถาม**: กรณีใดที่ `build_plan()` จะตอบ `operation: "no_change"` และ `changes` เป็นอย่างไร?
    - **ตอบ**: เมื่อค่าของทั้ง 3 ฟิลด์ตรงกันทั้งหมด และ `changes` จะเป็น dict ว่าง `{}`
28. **ถาม**: คำสั่ง `action: delete` มีการเรียกใช้งานฟังก์ชัน `build_plan()` ใน Part 2 หรือไม่?
    - **ตอบ**: **ไม่มี** การลบ interface จัดการแยกต่างหากใน Part 3 โดยตรง

---

### หมวดที่ 4: Network Automation Backends, Protocols และ Data Models (ข้อ 29 - 38)
29. **ถาม**: จับคู่ Method กับ Action ที่ระบบรองรับได้อย่างถูกต้องอย่างไร?
    - **ตอบ**:
      - `restconf`: `status`, `plan`, `apply`
      - `netconf`: `status`, `plan`, `apply`
      - `ansible`: `apply`
      - `netmiko-textfsm`: `status`, `delete`
30. **ถาม**: หากส่ง `method: restconf` ร่วมกับ `action: delete` จะได้รับผลลัพธ์ใด?
    - **ตอบ**: `{"status": "error", "result": "invalid_action"}`
31. **ถาม**: Backend ใดเป็น backend เดียวที่รองรับการ `delete` interface?
    - **ตอบ**: `netmiko-textfsm`
32. **ถาม**: YANG Data Model ใดที่ใช้สำหรับอ่านสถานะ (Status / Read) ใน RESTCONF และ NETCONF?
    - **ตอบ**: Vendor-Neutral Model ได้แก่ `ietf-interfaces` และ `ietf-ip`
33. **ถาม**: YANG Data Model ใดที่ใช้สำหรับเขียนคอนฟิก (Apply / Write) ใน RESTCONF และ NETCONF?
    - **ตอบ**: Vendor-Specific Native Model ได้แก่ `Cisco-IOS-XE-native`
34. **ถาม**: เพราะเหตุใด RESTCONF จึงใช้ HTTP Method `PUT` ในการ `apply` interface แทนที่จะใช้ `POST` หรือ `PATCH`?
    - **ตอบ**: เพื่อแทนที่ (Replace) ทรัพยากรเดิมทั้งหมดแบบ Idempotent ป้องกันการเกิด Secondary IP คั่งค้าง
35. **ถาม**: ใน RESTCONF และ NETCONF หากต้องการให้ interface มีสถานะ `admin_state: up` จะต้องส่งคอนฟิกอย่างไร?
    - **ตอบ**: ต้อง **ละเว้น (omit)** แท็ก `<shutdown/>` หรือคีย์ `"shutdown"` ออกไปจากคอนฟิก
36. **ถาม**: ใน NETCONF คำสั่งที่ใช้ในการแทนที่คอนฟิก Loopback ทั้งก้อนคืออะไร?
    - **ตอบ**: คำสั่ง `<edit-config>` ส่งไปยัง target `<running>` โดยใส่ attribute `nc:operation="replace"` ที่แท็ก `<Loopback>`
37. **ถาม**: ใน NETCONF หาก description มีตัวอักษรพิเศษเช่น `&` หรือ `<` โค้ดป้องกัน XML syntax error อย่างไร?
    - **ตอบ**: ใช้ฟังก์ชัน `xml.sax.saxutils.escape()` เพื่อแปลงเป็น entity เช่น `&amp;` และ `&lt;`
38. **ถาม**: หากสั่ง `delete_interface` บน Interface ที่ไม่ใช่ Loopback เช่น `GigabitEthernet1` ระบบจะตอบกลับอย่างไร?
    - **ตอบ**: `{"status": "error", "result": "backend_failed"}` เพราะระบบป้องกันความปลอดภัยโดยอนุญาตให้ลบเฉพาะ `Loopback<number>` เท่านั้น

---

### หมวดที่ 5: Ansible, Netmiko, การทดสอบ และเกณฑ์การตรวจ (ข้อ 39 - 50)
39. **ถาม**: ใน Ansible Playbook เหตุใดโมดูล `cisco.ios.ios_config` จึงต้องใส่ `defaults: true`?
    - **ตอบ**: เพื่อให้สามารถเปรียบเทียบกับค่า Default ของ Cisco IOS ได้ (เช่น `no shutdown`) ทำให้การรันซ้ำมีความเป็น Idempotent และรายงาน `changed=0`
40. **ถาม**: เหตุใดใน Ansible Playbook การกำหนดค่า shutdown จึงต้องเขียนว่า `shutdown | bool`?
    - **ตอบ**: เพราะตัวแปรใน Ansible ที่ส่งมาอาจเป็น string `"false"` ซึ่งใน Jinja2 ค่า string ที่ไม่ว่างจะถูกมองว่าเป็น True จึงต้องใส่ `| bool` เพื่อแปลงเป็น boolean ที่แท้จริง
41. **ถาม**: Netmiko ทำการอ่านสถานะของ interface ด้วยคำสั่ง CLI ใดบ้าง?
    - **ตอบ**: `show ip interface <name>` และ `show interfaces description`
42. **ถาม**: เหตุใด Netmiko จึงต้องมีตรรกะการแปลงชื่อย่อ (Abbreviation Normalization)?
    - **ตอบ**: เพราะ Cisco IOS มักย่อชื่อในคำสั่ง `show interfaces description` เช่น `Loopback123` จะถูกย่อเป็น `Lo123`
43. **ถาม**: เมื่อทำการลบ interface ที่ไม่มีอยู่แล้วบน Router (Delete ซ้ำ) ระบบจะตอบกลับอย่างไร?
    - **ตอบ**: `{"status": "ok", "result": "not_found", "interface": null}` (ถือเป็นการทำงานที่สำเร็จแบบ Idempotent ไม่ใช่ error)
44. **ถาม**: รหัสข้อผิดพลาดระดับ Backend (Backend Errors) มีกี่ประเภท และอะไรบ้าง?
    - **ตอบ**: มี 3 ประเภท คือ `authentication_failed`, `connection_failed`, และ `backend_failed`
45. **ถาม**: หากเกิด `ncclient.transport.errors.TransportError` จะถูกแมปเป็นข้อผิดพลาดใด?
    - **ตอบ**: `connection_failed`
46. **ถาม**: หากเกิด `ncclient.operations.rpc.RPCError` จะถูกแมปเป็นข้อผิดพลาดใด?
    - **ตอบ**: `backend_failed`
47. **ถาม**: การสอบ Take-home มีคะแนนรวมเท่าใด แบ่งเป็นส่วนใดบ้าง?
    - **ตอบ**: รวม 20 คะแนน แบ่งเป็น คะแนน CI 10 คะแนน (Public + Hidden tests) และ คะแนน Live Test 10 คะแนน (สุ่มตรวจ 20 กรณี)
48. **ถาม**: นักศึกษาสามารถส่งตรวจจริงด้วยคำสั่ง `grade` ได้สูงสุดกี่ครั้ง?
    - **ตอบ**: สูงสุดไม่เกิน 10 ครั้ง (ส่วนคำสั่ง `register`, `verify`, `score` ไม่จำกัดจำนวนครั้งและไม่เสียโควตา)
49. **ถาม**: ในขั้นตอน Live Test ช่วง IP ใดที่ถูกสงวนไว้สำหรับระบบตรวจของผู้สอน และห้ามมิให้นักศึกษาใช้ทดลองเอง?
    - **ตอบ**: ช่วง `192.0.2.128/27` (และ Interface ทดสอบจะถูกสร้างบน Router `10.0.29.101`)
50. **ถาม**: สคริปต์ `scripts/check_webhook_image.py` ทำหน้าที่อะไรใน Student CI?
    - **ตอบ**: ทำหน้าที่ Smoke Test แบบ Offline ภายใน Docker Container Image ที่เพิ่ง Build เสร็จ เพื่อยืนยันว่า Import โมดูลได้ครบถ้วน และ HTTP Endpoint `/health` กับ `/webhook` ตอบสนองถูกต้องตาม spec ก่อนเริ่มการตรวจ Live
