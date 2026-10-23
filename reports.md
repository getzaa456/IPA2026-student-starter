# รายงานสรุปเนื้อหาและการทำงานของโค้ด (IPA2026 Final Exam)
> เอกสารนี้จัดทำขึ้นเพื่ออธิบายรายละเอียดการทำงาน สถาปัตยกรรม และตรรกะเบื้องหลังโค้ดในแต่ละ Part อย่างละเอียด เพื่อใช้ทบทวนและเตรียมสอบข้อสอบปรนัย (MCQ) 40 ข้อ

---

## ภาพรวมสถาปัตยกรรมระบบ (System Architecture Overview)

ระบบนี้เป็น **ChatOps Bot สำหรับบริหารจัดการ Network Router อัตโนมัติผ่าน Cisco Webex**
โดยหลักการทำงานคือ:
1. ผู้ใช้ (นักศึกษา/ผู้ตรวจ) ส่งข้อความโดย **@mention Bot** พร้อมแนบไฟล์คอนฟิก **YAML 1 ไฟล์** เข้ามาในห้อง Webex
2. Webex ส่ง Webhook Event (`messages/created`) ไปยัง HTTPS Tunnel (เช่น Cloudflare Tunnel) แล้วส่งต่อไปยัง Webhook Server ของ Bot (`POST /webhook`)
3. Webhook Server ตอบรับทันทีด้วย **HTTP 200 OK** (ยืนยันว่าได้รับ Event แล้ว)
4. Bot ดำเนินการแบบ Asynchronous / Background:
   - เรียก Webex API เพื่อดาวน์โหลดข้อมูลข้อความและไฟล์แนบ YAML
   - ตรวจสอบความถูกต้องของซองจดหมาย (Webex Envelope) และเนื้อหา YAML (Core Validation)
   - หากต้องคุยกับ Router จะส่งต่อไปยัง Dispatcher เพื่อสั่งงาน Backend ตามที่ระบุ (`restconf`, `netconf`, `ansible`, `netmiko-textfsm`)
   - ส่งผลลัพธ์กลับไปยังห้อง Webex เดิมเป็นข้อความ JSON ผ่าน Webex REST API (`POST /v1/messages`)

---

## Part 1: การตรวจสอบข้อความ Webex และโครงสร้างไฟล์ YAML (Envelope & YAML Core Validation)

### 1. วัตถุประสงค์ของ Part 1
Part 1 ทำหน้าที่เป็น **Security Gate & Input Validation** หน้าด่านแรก เพื่อคัดกรองคำขอที่ผิดรูปแบบ ไม่ถูกต้อง หรือไม่ได้ตั้งใจส่งถึง Bot ตัวนี้ ทิ้งไปทันทีก่อนที่จะส่งต่อไปแตะต้อง Network Router โดยใน Part 1 จะยังไม่มีการติดต่อหรือแก้ไข Router ใดๆ ทั้งสิ้น

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
   - *จุดสำคัญสำหรับข้อสอบ*: Webex API ส่งรายชื่อคนที่ถูก mention มาเป็น **Person ID (Base64 string)** ไม่ใช่ Display Name (เช่น `@66070123`) และไม่ใช่ plain text หากไม่มีชื่อ Bot ใน list หรือ list ว่าง จะตอบกลับทันทีเป็น:
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

#### 3.1 `process_request_file(path)`
- พยายามเปิดไฟล์ YAML ด้วย `utf-8` และใช้ `yaml.safe_load(f)`
- หากเกิดข้อผิดพลาดในการ parse (Syntax error เช่น วงเล็บปิดไม่ครบ ลืมเว้นวรรค) หรือ root ของไฟล์ไม่ใช่ mapping (dict) เช่น เป็น list หรือว่างเปล่า จะตอบกลับทันที:
  ```json
  {"status": "error", "result": "invalid_yaml"}
  ```
- หากโครงสร้างไฟล์เป็น mapping (dict) จะส่งต่อไปให้ `validate_request(data)`

#### 3.2 `validate_request(data)` และลำดับการตรวจ (Precedence)
**ข้อสอบ MCQ มักถามลำดับการ return error อย่างละเอียด** โค้ดจะต้องตรวจสอบตามลำดับ 1 ถึง 6 อย่างเคร่งครัด หากผิดหลายข้อ ต้องส่ง error ของข้อที่อยู่ก่อนหน้าเสมอ:

1. **Version Check (`invalid_version`)**:
   - `version` ต้องระบุ และต้องเป็น **YAML integer ค่า `1`** เท่านั้น
   - *กับดักข้อสอบ*: ค่า `"1"` (string), `1.0` (float), หรือ `true` (boolean) ถือว่าผิดทั้งหมด!
   - ใน Python `isinstance(True, int)` จะได้ `True` ดังนั้นโค้ดจึงต้องเช็ก `type(version) is int and version == 1` อย่างเข้มงวด
2. **Router Check (`missing_router` -> `invalid_router`)**:
   - ต้องมีฟิลด์ `router` และไม่เป็นค่าว่าง มิฉะนั้นตอบ `missing_router`
   - ค่าของ `router` ต้องเป็นหนึ่งใน Router ที่ได้รับอนุญาต 5 หมายเลขเท่านั้น:
     - `10.0.29.101` (Grader/Lab router)
     - `10.0.29.102`
     - `10.0.29.103`
     - `10.0.29.104`
     - `10.0.29.105`
     - หากเป็น IP อื่น ตอบ `invalid_router`
3. **Method Check (`missing_method` -> `invalid_method`)**:
   - ต้องมีฟิลด์ `method` มิฉะนั้นตอบ `missing_method`
   - ต้องเป็นหนึ่งใน 4 ค่านี้เท่านั้น:
     - `restconf`
     - `netconf`
     - `ansible`
     - `netmiko-textfsm`
     - หากไม่ใช่ ตอบ `invalid_method`
4. **Action Check (`missing_action` -> `invalid_action`)**:
   - ต้องมีฟิลด์ `action` มิฉะนั้นตอบ `missing_action`
   - ตรวจสอบความเข้ากันได้ระหว่าง `method` และ `action` (Method-Action Compatibility Table):
     | Method | status | plan | apply | delete |
     |---|:---:|:---:|:---:|:---:|
     | `restconf` | ✓ | ✓ | ✓ | ✗ |
     | `netconf` | ✓ | ✓ | ✓ | ✗ |
     | `ansible` | ✗ | ✗ | ✓ | ✗ |
     | `netmiko-textfsm` | ✓ | ✗ | ✗ | ✓ |
   - หาก method รู้จัก แต่ action ไม่รองรับ (เช่น `restconf` + `delete` หรือ `ansible` + `status`) จะต้องตอบ `invalid_action`
5. **Desired State Check (`missing_desired` -> `missing_interface` -> `missing_interface_name`)**:
   - ต้องมี mapping `desired` มิฉะนั้นตอบ `missing_desired`
   - ภายใต้ `desired` ต้องมี mapping `interface` มิฉะนั้นตอบ `missing_interface`
   - ภายใต้ `desired.interface` ต้องมี `name` ที่ไม่ว่างเปล่า มิฉะนั้นตอบ `missing_interface_name`
6. **Complete State for `plan` and `apply` Only**:
   - หาก `action` เป็น `plan` หรือ `apply` จะต้องส่งค่าคอนฟิกที่ครบถ้วน ได้แก่:
     - `ipv4`: ต้องมีและไม่ว่าง มิฉะนั้นตอบ `missing_ipv4`
     - `description`: ต้องมี (เป็น string) มิฉะนั้นตอบ `missing_description`
     - `admin_state`: ต้องมีและไม่ว่าง มิฉะนั้นตอบ `missing_admin_state`
     - ค่าของ `admin_state` ต้องเป็น `"up"` หรือ `"down"` เท่านั้น มิฉะนั้นตอบ `invalid_admin_state`
   - *ข้อยกเว้นสำคัญสำหรับ `status` และ `delete`*:
     - ทั้งสอง action นี้ต้องการเพียง `desired.interface.name` เท่านั้น
     - แม้ผู้ใช้จะใส่ `ipv4`, `description`, หรือใส่ `admin_state: invalid-value` มาด้วย ตัวตรวจจะ **ละเว้น (ignore)** ค่าเหล่านี้ และไม่ถือเป็นข้อผิดพลาด!

#### 3.3 ผลลัพธ์เมื่อการตรวจสอบ Part 1 สำเร็จ
หากข้อมูลทุกอย่างถูกต้องครบถ้วน จะส่งคืน:
```json
{
  "status": "ok",
  "result": "accepted"
}
```

---

### 4. สรุปประเด็นสำคัญสำหรับเตรียมตัวสอบ MCQ 40 ข้อ (Part 1 Checklist)
1. **HTTP 200 ของ Webhook หมายถึงอะไร?**
   - หมายถึง Server ได้รับข้อความ/event แล้ว **ไม่ใช่** หมายความว่าคำสั่งใน YAML ทำงานเสร็จสิ้น
2. **Webex Person ID คืออะไร?**
   - เป็น unique base64 string ที่ Webex กำหนดให้ bot ไม่ใช่ username หรือ student ID
3. **ถ้า YAML มี `version: 2` และไม่มี `router` จะได้ error อะไร?**
   - ตอบ `invalid_version` เพราะตรวจ `version` ก่อน `router` (Precedence Order)
4. **ถ้าส่ง `restconf` กับ `action: delete` จะได้ error อะไร?**
   - ตอบ `invalid_action` เพราะ RESTCONF ใน lab นี้รองรับเฉพาะ `status`, `plan`, `apply` ส่วนการ delete ให้ใช้ `netmiko-textfsm`
5. **คำสั่งใดต้องระบุ `ipv4`, `description`, `admin_state`?**
   - เฉพาะ `plan` และ `apply` เท่านั้น (ส่วน `status` และ `delete` ดูเฉพาะ `name`)

---

## Part 2: การวางแผนและการเปรียบเทียบสถานะ (Planner & Desired State Engine)

### 1. วัตถุประสงค์ของ Part 2
Part 2 จำลองหัวใจสำคัญของ **Infrastructure as Code (IaC)** และ **Declarative Automation** (คล้ายกับหลักการทำงานของ Terraform หรือ Kubernetes Controller) นั่นคือการนำ **Desired State (สถานะที่ต้องการ)** มาเปรียบเทียบกับ **Current State (สถานะจริงปัจจุบันบน Router)** เพื่อคำนวณแผนการเปลี่ยนแปลง (Execution Plan) ที่แน่นอน (Deterministic) และไม่ส่งผลกระทบซ้ำซ้อน (Idempotent)

ไฟล์ที่เกี่ยวข้อง:
- `app/planner.py`: ฟังก์ชันหลัก `build_plan(desired_interface, current_interface)`
- `sample-tests/part2/fixtures/` และ `sample-tests/part2/cases/`: ชุดทดสอบที่กำหนดตาม spec (รวมทั้งชุดทดสอบเพิ่มเติม 3 ชุดที่นักศึกษาต้องสร้างขึ้น)

---

### 2. ขอบเขตและหน้าที่ของ Planner (`specs/plan-spec-v1.md`)
- **ไม่เชื่อมต่อกับ Router จริง**: Planner เป็น pure function ทางตรรกศาสตร์ รับข้อมูล Python dict เข้ามา แล้วประมวลผลส่ง dict ผลลัพธ์ออกไป
- **ไม่เกี่ยวข้องกับการ Parse ข้อมูลดิบ**: ข้อมูล `current_interface` ที่ส่งเข้ามาจะถูกแปลงให้อยู่ในรูป Normalized dict เรียบร้อยแล้ว (โดย Backend ใน Part 3)
- **ไม่รองรับคำสั่ง `delete`**: การลบ interface ไม่จัดเป็น operation ใน Planner (การลบจะถูกจัดการแยกต่างหากใน Part 3 ด้วย Netmiko)

---

### 3. ฟังก์ชันหลัก `build_plan(desired_interface, current_interface)`

#### 3.1 ตัวแปรและฟิลด์ที่จัดการ (Managed Fields)
- **Resource Identifier**: `name` (เช่น `"Loopback123"`)
  - ใช้ระบุ interface เป้าหมายเท่านั้น
  - **ข้อควรระวังสำหรับข้อสอบ**: ฟิลด์ `name` **ต้องไม่ปรากฏ** ใน dictionary `changes` เด็ดขาด!
- **Managed Fields**: ฟิลด์ที่มีสิทธิ์ถูกเปรียบเทียบและบันทึกลงใน `changes` มีเพียง 3 ฟิลด์เท่านั้น:
  1. `ipv4`
  2. `description`
  3. `admin_state`

#### 3.2 การตัดสินใจเลือก `operation` ทั้ง 3 รูปแบบ

##### ก. กรณี `create`
- **เงื่อนไข**: เมื่อ `current_interface is None` (แปลว่ายังไม่มี interface นี้อยู่บน router)
- **โครงสร้างของ `changes`**:
  - ต้องใส่ครบทั้ง 3 managed fields (`ipv4`, `description`, `admin_state`)
  - ระบุเฉพาะค่าปลายทาง `"to"` เท่านั้น (ไม่มี `"from"` เพราะของเดิมไม่มีอยู่)
  - ตัวอย่างผลลัพธ์:
    ```json
    {
      "status": "ok",
      "result": "planned",
      "operation": "create",
      "changes": {
        "ipv4": {"to": "172.23.123.1/32"},
        "description": {"to": "IPA2026-66070123"},
        "admin_state": {"to": "up"}
      }
    }
    ```

##### ข. กรณี `update`
- **เงื่อนไข**: เมื่อมี `current_interface` อยู่แล้วบน Router แต่มี managed field อย่างน้อย 1 ฟิลด์ที่มีค่าไม่ตรงกับ `desired_interface`
- **โครงสร้างของ `changes`**:
  - ใส่ **เฉพาะฟิลด์ที่มีค่าแตกต่างกันเท่านั้น** (ฟิลด์ที่ค่าตรงกันแล้วไม่ต้องใส่ลงมา)
  - แต่ละฟิลด์ที่เปลี่ยนต้องแสดงทั้งค่าเดิม `"from"` และค่าใหม่ `"to"`
  - ตัวอย่างผลลัพธ์:
    ```json
    {
      "status": "ok",
      "result": "planned",
      "operation": "update",
      "changes": {
        "description": {
          "from": "OLD-DESCRIPTION",
          "to": "IPA2026-66070123"
        }
      }
    }
    ```

##### ค. กรณี `no_change`
- **เงื่อนไข**: เมื่อ `current_interface` มีอยู่แล้ว และค่าของ `ipv4`, `description`, `admin_state` ตรงกับ `desired_interface` ครบทุกฟิลด์
- **โครงสร้างของ `changes`**:
  - ต้องเป็น dictionary ว่าง `{}` เสมอ
  - ตัวอย่างผลลัพธ์:
    ```json
    {
      "status": "ok",
      "result": "planned",
      "operation": "no_change",
      "changes": {}
    }
    ```

---

### 4. คุณสมบัติสำคัญของระบบ Automation ที่ออกข้อสอบบ่อย

1. **Determinism (ความแน่นอนของผลลัพธ์)**:
   - สำหรับ input (`desired` และ `current`) ชุดเดิม ผลลัพธ์ของ `build_plan()` จะต้องได้ `operation` และ `changes` เหมือนเดิมทุกครั้ง 100% ไม่ขึ้นกับเวลาหรือลำดับการรัน
2. **Idempotency (ความเป็นนิจศีล / ทำซ้ำได้โดยผลไม่เพี้ยน)**:
   - หากสถานะปัจจุบันบนอุปกรณ์ตรงกับความต้องการอยู่แล้ว (`no_change`) ระบบจะไม่ส่งคำสั่งแก้ไขไปยัง router ซ้ำอีก ช่วยป้องกัน network flap และความเสี่ยงในการ restart service
3. **Drift Detection (การตรวจจับความคลาดเคลื่อน)**:
   - หากมีวิศวกรไปแอบเปลี่ยนคอนฟิกหน้างาน (Out-of-band change) เช่น เปลี่ยน description แผนการรันแบบ `update` จะตรวจพบและแสดงค่า `from` (ค่าที่หลุดไป) และ `to` (ค่าที่ถูกต้องตามโค้ด) เพื่อดึงคอนฟิกกลับมาให้ตรงตามที่นิยามไว้

---

### 5. ชุดทดสอบที่สร้างเพิ่มเติมใน Part 2 (Student-created Test Cases)
ตามข้อกำหนดของ Spec นักศึกษาต้องสร้าง test cases เพิ่มเติมอย่างน้อย 3 กรณี:
1. `05-update-ipv4-only.yaml`: ทดสอบกรณีแก้ไขเฉพาะหมายเลข IP address (`ipv4`)
2. `06-update-admin-state-only.yaml`: ทดสอบกรณีแก้ไขเฉพาะสถานะเปิด/ปิด interface (`admin_state` จาก `up` เป็น `down`)
3. `07-update-all-three-fields.yaml`: ทดสอบกรณีแก้ไขพร้อมกันทั้ง 3 ฟิลด์ (`ipv4`, `description`, `admin_state`)

---

## Part 3: การเชื่อมต่อและการสั่งการ Network Router ผ่าน Backend ต่างๆ (Network Automation Backends)

### 1. วัตถุประสงค์ของ Part 3
Part 3 เป็นส่วนที่นำโปรโตคอลและเครื่องมือ Network Automation สมัยใหม่มาพัฒนาเป็น Adapter เพื่อติดต่อกับ Cisco IOS XE Router จริง โดยแปลงข้อมูลระหว่างคำสั่งเฉพาะของแต่ละเทคโนโลยี (JSON, XML, CLI, Playbook) กับโครงสร้างข้อมูลมาตรฐาน (Normalized Interface State) ของระบบ

ไฟล์ที่เกี่ยวข้อง:
- `app/backends/planning.py`: ตัวเชื่อมการวางแผน (Plan Wrapper) สำหรับ Backend ที่รองรับ plan
- `app/backends/restconf.py`: จัดการ Router ด้วย RESTCONF (HTTP/JSON)
- `app/backends/netconf.py`: จัดการ Router ด้วย NETCONF (SSH/XML)
- `app/backends/ansible.py`: จัดการ Router ด้วย Ansible Playbook & IOS Module
- `app/backends/netmiko_textfsm.py`: จัดการ Router ด้วย Netmiko (SSH CLI) ร่วมกับ TextFSM Template
- `ansible/apply_interface.yml` และ `ansible/inventory.ini`: Playbook และ Inventory สำหรับ Ansible

---

### 2. ตารางความสามารถของแต่ละ Backend (Capability Matrix)
*จุดสำคัญมากสำหรับข้อสอบ*: แต่ละเทคโนโลยีมีความเหมาะสมกับงานที่แตกต่างกัน:
| Method | Protocol / Port | Data Format | status | plan | apply | delete |
|---|---|---|:---:|:---:|:---:|:---:|
| **RESTCONF** | HTTPS (443) | JSON (`application/yang-data+json`) | ✓ | ✓ | ✓ | ✗ |
| **NETCONF** | SSH (830) | XML (RPC) | ✓ | ✓ | ✓ | ✗ |
| **Ansible** | SSH (22) via Paramiko | YAML / CLI (`cisco.ios.ios_config`) | ✗ | ✗ | ✓ | ✗ |
| **Netmiko + TextFSM** | SSH (22) | Text CLI / Regex Templates | ✓ | ✗ | ✗ | ✓ |

---

### 3. แบบจำลองข้อมูล YANG (Frozen YANG Models)
ในการทดสอบจริง มีการแบ่งแยก Data Model สำหรับการ "อ่าน" และ "เขียน" อย่างชัดเจน:
1. **การอ่านสถานะ (Status / Read)**:
   - ใช้โมเดลมาตรฐานกลางที่ไม่ผูกติดกับยี่ห้อ (Vendor-Neutral / IETF Standard):
     - `ietf-interfaces` (rev: 2014-05-08)
     - `ietf-ip` (rev: 2014-06-16)
   - ข้อดี: ใช้โครงสร้าง schema เดียวกันอ่านค่าสถานะจากอุปกรณ์ได้หลาย vendor
2. **การเขียนคอนฟิก (Apply / Write)**:
   - ใช้โมเดลเฉพาะของอุปกรณ์ Cisco (Vendor-Specific / Native Model):
     - `Cisco-IOS-XE-native` (rev: 2018-07-27)
   - ข้อดี: มีความสามารถครอบคลุมฟังก์ชันเฉพาะตัวของ Cisco IOS XE และสามารถแทนที่ Loopback ทั้งก้อนได้โดยไม่ทิ้ง IP เก่าค้างไว้เป็น Secondary IP

---

### 4. เจาะลึกการทำงานของแต่ละ Backend

#### 4.1 Planning Wrapper (`app/backends/planning.py`)
- ฟังก์ชัน: `plan_interface(router, desired_interface, get_interface_state)`
- **หลักการทำงาน**:
  1. เรียก `get_interface_state(router, interface_name)` ของ backend นั้นๆ เพื่ออ่านค่าจริง
  2. หาก backend ตอบ error (เช่น ต่อ router ไม่ติด) จะส่ง error นั้นกลับทันทีโดยไม่คำนวณ plan
  3. หากตอบ `not_found` จะตั้ง `current_interface = None`
  4. หากตอบ `found` จะดึง `current_interface = response["interface"]`
  5. ส่งไปคำนวณต่อด้วย `build_plan(desired_interface, current_interface)` จาก Part 2
- *เหตุผลทางสถาปัตยกรรม*: เพื่อไม่ให้มีการเขียนโค้ดเปรียบเทียบ state ซ้ำซ้อน (Don't Repeat Yourself - DRY) ในแต่ละ backend

#### 4.2 RESTCONF Backend (`app/backends/restconf.py`)
- **Protocol**: ทำงานบน HTTP/1.1 หรือ HTTP/2 ผ่าน TLS (HTTPS พอร์ต 443)
- **Content-Type / Accept Header**: `application/yang-data+json`
- **การอ่านสถานะ (`get_interface_state`)**:
  - เมธอด: `GET`
  - URL: `https://{router}/restconf/data/ietf-interfaces:interfaces/interface={interface_name}`
  - การแปลงข้อมูล (Normalization):
    - แปลง `ip` และ `netmask` จากก้อน `ietf-ip:ipv4` ให้กลายเป็นรูปแบบ CIDR (เช่น `172.23.123.1/32`) โดยใช้คลาส `IPv4Interface`
    - แปลงฟิลด์ boolean `enabled`: ถ้า `true` -> `admin_state: "up"`, ถ้า `false` -> `admin_state: "down"`
    - หาก HTTP Status Code เป็น `404` แสดงว่าไม่มี interface ตอบ `result: "not_found"`
- **การคอนฟิก (`apply_interface`)**:
  - เมธอด: `PUT` (ใช้ PUT เพื่อแทนที่ resource เดิมทั้งหมดแบบ Idempotent)
  - URL: `https://{router}/restconf/data/Cisco-IOS-XE-native:native/interface/Loopback={number}`
  - Payload ใช้โมเดล native:
    ```json
    {
      "Cisco-IOS-XE-native:Loopback": {
        "name": 123,
        "description": "...",
        "ip": {
          "address": {
            "primary": {"address": "...", "mask": "..."}
          }
        }
      }
    }
    ```
    - หาก `admin_state == "down"` จะเพิ่ม `"shutdown": [null]` ลงในก้อน Loopback
    - หาก `admin_state == "up"` จะ **ละเว้น** คีย์ shutdown ออกไป (เพื่อให้ interface เปิดใช้งาน)
  - HTTP Status Code ที่ถือว่าสำเร็จ: `200`, `201`, `204`

#### 4.3 NETCONF Backend (`app/backends/netconf.py`)
- **Protocol**: ทำงานบน SSH Subsystem พอร์ต 830
- **Library หลัก**: `ncclient`
- **การอ่านสถานะ (`get_interface_state`)**:
  - ใช้คำสั่ง `<get-config>` ด้วย Subtree Filter:
    ```xml
    <interfaces xmlns="urn:ietf:params:xml:ns:yang:ietf-interfaces">
      <interface><name>{interface_name}</name></interface>
    </interfaces>
    ```
  - Parse ผลลัพธ์ XML ด้วย `xml.etree.ElementTree` ดึงค่า name, description, enabled, ip, netmask มาแปลงเป็น Normalized Interface State
- **การคอนฟิก (`apply_interface`)**:
  - ใช้คำสั่ง `<edit-config>` ส่งไปยัง Datastore `<running>`
  - ใช้ Attribute `nc:operation="replace"` ที่แท็ก `<Loopback>` ภายใต้ Namespace `http://cisco.com/ns/yang/Cisco-IOS-XE-native`
  - หาก `admin_state == "down"` จะใส่แท็ก `<shutdown/>` เพิ่มเข้าไป
  - ประโยชน์ของการใช้ `replace`: ลบ secondary IP address เดิมที่อาจค้างอยู่ออกไปโดยอัตโนมัติ

#### 4.4 Ansible Backend (`app/backends/ansible.py`)
- **หน้าที่**: รองรับเฉพาะการ `apply` เท่านั้น (Apply-only)
- **Module & Connection Plugin**:
  - ใช้โมดูล `cisco.ios.ios_config`
  - ใช้ connection plugin `ansible.netcommon.network_cli`
- **การทำงานของ Playbook (`ansible/apply_interface.yml`)**:
  - แปลง Desired State ให้เป็น IOS CLI Commands:
    ```text
    interface Loopback123
      description IPA2026-66070123
      ip address 172.23.123.1 255.255.255.255
      no shutdown (หรือ shutdown)
    ```
  - *จุดออกข้อสอบสำคัญ*: มีการเปิดออปชัน `defaults: true` เพื่อให้ Ansible สามารถเปรียบเทียบคำสั่งที่เป็น default ของ Cisco IOS ได้ (เช่น ปกติ interface up จะไม่มีคำบรรทัด `no shutdown` โชว์ใน running-config แต่ถ้าใส่ `defaults: true` Ansible จะเข้าใจว่าสถานะตรงกันแล้ว และรายงาน `changed=0` ไม่ยิงคำสั่งซ้ำ)

#### 4.5 Netmiko + TextFSM Backend (`app/backends/netmiko_textfsm.py`)
- **หน้าที่**: รองรับ 2 การทำงานคือ `status` และ `delete`
- **การอ่านสถานะ (`get_interface_state`)**:
  - รัน 2 คำสั่ง CLI แบบ Read-only:
    1. `show ip interface <name>`: ใช้ template NTC TextFSM เพื่อสกัด IP address, prefix length และ link status (หากเจอคำว่า `"administratively down"` จะแปลงเป็น `admin_state: "down"`, นอกนั้นเป็น `"up"`)
    2. `show interfaces description`: ดึง description ของ interface
  - *การจัดการชื่อย่อ (Abbreviation Normalization)*: ในคำสั่ง `show interfaces description` ของ Cisco IOS ชื่อ Loopback มักถูกย่อ เช่น `Loopback123` จะถูกแสดงเป็น `Lo123` โค้ดจะต้องทำ normalization ให้จับคู่กันได้ถูกต้อง
- **การลบ Interface (`delete_interface`)**:
  - เป็น **backend เดียวในระบบที่รองรับการลบ interface** (RESTCONF, NETCONF, Ansible ไม่รองรับ delete ในข้อสอบชุดนี้)
  - ขั้นตอนการทำงาน:
    1. ตรวจสอบสถานะก่อน: หากไม่มี interface อยู่แล้ว จะตอบ `not_found` ทันที (ถือเป็น Idempotent Delete)
    2. หากมีอยู่: ส่งคำสั่ง CLI `no interface <name>` เข้าไปใน config mode ผ่าน Netmiko
    3. ตรวจสอบยืนยัน (Verification): อ่านสถานะซ้ำอีกครั้ง ถ้าไม่พบ interface แล้ว จะตอบ `{"status": "ok", "result": "deleted"}`

---

### 5. การจัดการ Error แบบรวมศูนย์ (Backend Error Normalization)
เมื่อเกิดปัญหาในการเชื่อมต่อกับ Router ไม่ว่าจะมาจาก requests, ncclient, netmiko หรือ ansible จะต้องถูกแปลงให้อยู่ใน 1 ใน 3 รูปแบบมาตรฐานเสมอ:
1. `authentication_failed`: เมื่อใส่ username/password ผิด หรือไม่มีสิทธิ์เข้าถึงอุปกรณ์ (HTTP 401/403, SSH Auth Failed, PermissionError)
2. `connection_failed`: เมื่อไม่สามารถเชื่อมต่อ network ไปยัง IP ของ Router ได้ (Connection Timeout, Unreachable Host, SSH Connection Refused, ConnectionError)
3. `backend_failed`: เชื่อมต่อได้ แต่ Router ปฏิเสธคำสั่ง ไวยากรณ์ XML/JSON ผิด หรือเกิด RPC Error ภายใน Router

---

## Part 4: การเชื่อมต่อระบบครบวงจร, Webex Bot, Webhook Server และ Docker (Integration & ChatOps Deployment)

### 1. วัตถุประสงค์ของ Part 4
Part 4 เป็นส่วนที่นำโค้ดทั้งหมด (Part 1 ตรวจสอบ, Part 2 วางแผน, Part 3 เชื่อมต่อ Router) มาประกอบเข้าด้วยกันเป็นระบบ **ChatOps Webex Bot** ที่ใช้งานได้จริงบน Docker Container และสามารถสื่อสารกับ Cisco Webex API และ Router ในสภาพแวดล้อม Live Test

ไฟล์ที่เกี่ยวข้อง:
- `app/dispatcher.py`: ตัวสลับเส้นทาง (Routing Switchboard) กระจายงานไปยัง Backend ต่างๆ
- `app/integration.py`: ตัวเชื่อมโยงภาพรวม (Orchestrator) ระหว่าง Webex Envelope, การตรวจสอบ YAML และการส่งต่อให้ Dispatcher
- `app/webex_client.py`: คลาสติดต่อกับ Webex REST API (`https://webexapis.com/v1`)
- `app/webhook_server.py`: HTTP Server รับ Event จาก Webex Webhook และ Worker คอยส่งคำสั่งแบบ Background
- `Dockerfile` & `compose.yaml`: การ Build Container Image และการตั้งค่า Deployment

---

### 2. เจาะลึกการทำงานของแต่ละโมดูลใน Part 4

#### 2.1 Dispatcher (`app/dispatcher.py`)
ทำหน้าที่เป็นศูนย์กลางกระจายคำขอ (`dispatch_request(data)`):
- รับ dictionary ของคำขอที่ผ่านการ Validate มาแล้ว
- ดึงข้อมูล `method`, `action`, `router` และ `interface`
- **ความแตกต่างของการส่งพารามิเตอร์ (จุดสำคัญสำหรับข้อสอบ)**:
  - คำสั่ง `status` และ `delete`: ต้องการเพียงชื่อ interface เท่านั้น จึงส่ง `(router, interface["name"])`
  - คำสั่ง `plan` และ `apply`: ต้องการคอนฟิก interface ทั้งหมด จึงส่ง `(router, interface)` (ก้อน dict)

#### 2.2 Integration Orchestrator (`app/integration.py`)
ทำหน้าที่เป็น Pipeline ควบคุมลำดับขั้นตอน:
1. เรียก `validate_webex_envelope(mentioned_people, attachment_path, bot_person_id)`
2. หาก envelope ไม่ผ่าน ให้หยุดทันที และส่ง error กลับ
3. เปิดอ่านไฟล์แนบ YAML และ parse ข้อมูล (ถ้าอ่านไม่ได้ ตอบ `invalid_yaml`)
4. เรียก `validate_request(data)` จาก Part 1 เพื่อตรวจสอบความถูกต้องตามกฎ Precedence
5. หาก YAML ไม่ถูกต้อง ให้หยุดทันที และส่ง error กลับ (**ไม่ส่งต่อไปยัง Router**)
6. หากถูกต้องทุกประการ ส่งต่อไปยัง `dispatch_request(data)` เพื่อสั่งงาน Router จริง

#### 2.3 Webex Client (`app/webex_client.py`)
ติดต่อกับ Webex Cloud API (`https://webexapis.com/v1`) ผ่าน HTTP:
- `get_message(message_id)`: เรียก `GET /messages/{message_id}` เพื่อดูข้อความ, คนที่ mention, และลิงก์ดาวน์โหลดไฟล์ (`files`)
- `download_file(file_url)`: เรียก `GET {file_url}` พร้อมส่ง Header `Authorization: Bearer <token>` เพื่อดาวน์โหลดไฟล์ YAML
- `send_message(room_id, text)`: เรียก `POST /messages` ส่งข้อความผลลัพธ์เป็น JSON กลับไปยังห้อง Webex

#### 2.4 Webhook Server & Event Handler (`app/webhook_server.py`)
- **HTTP Server (`make_http_handler`)**:
  - `GET /health`: สำหรับ Docker Healthcheck ตอบ `200 {"status": "ok", "result": "healthy"}`
  - `POST /webhook`:
    - ตรวจสอบขนาด Body (จำกัดที่ 1 ถึง 1,000,000 bytes)
    - Parse JSON Body หากผิดรูปแบบ ตอบ `400 {"status": "error", "result": "invalid_event"}`
    - หากถูกต้อง ตอบรับทันทีด้วย **`200 {"status": "ok", "result": "accepted"}`** และนำ event ส่งเข้าคิวทำงานเบื้องหลัง (Non-blocking)
- **การประมวลผลเบื้องหลัง (Background Worker)**:
  - ใช้ `queue.Queue` และ Worker Thread ประมวลผล **ทีละรายการตามลำดับ (Sequential Processing)** เพื่อป้องกันการส่งคำสั่งชนกันบน Router
- **Event Handler (`WebexEventHandler`)**:
  - **การป้องกัน Event Loop**: ตรวจสอบ `personId` ของผู้ส่ง หากตรงกับ `bot_person_id` ของตนเอง ให้ข้ามทันที (เพื่อไม่ให้ bot ตอบข้อความตัวเองวนลูป)
  - **การตรวจไฟล์แนบ**:
    - ถ้าไม่มีไฟล์แนบ (`len(files) == 0`): ส่ง error `no_yaml` ไปยังห้อง Webex
    - ถ้ามีไฟล์แนบมากกว่า 1 ไฟล์ (`len(files) > 1`): ส่ง error `multiple_attachments` ไปยังห้อง Webex ทันทีโดยไม่ดาวน์โหลดไฟล์
    - ถ้ามีไฟล์แนบ 1 ไฟล์พอดี: ดาวน์โหลดไฟล์ บันทึกลง Temporary File ส่งไปประมวลผล แล้วลบไฟล์ทิ้งทันทีหลังทำงานเสร็จ (Clean up)
  - **การตอบกลับ**: ส่งผลลัพธ์ JSON กลับไปยัง `roomId` ของห้องที่ส่งคำขอเข้ามา (ไม่ Fix room ID ตายตัว เพื่อให้รองรับทั้งห้องทดลองและห้องสอบ)

---

### 3. Dockerfile, Docker Compose และ Environment Variables
- **Dockerfile**:
  - Base Image: `python:3.12-slim`
  - ติดตั้ง dependencies จาก `requirements.txt`
  - Copy โฟลเดอร์ `app/` และ `ansible/` เข้าไปใน Container
  - รันคำสั่งเริ่มต้น: `CMD ["python", "-m", "app.webhook_server"]`
- **Compose (`compose.yaml`)**:
  - ตั้งชื่อ Service: `webhook`
  - พอร์ต: `8000:8000`
  - Healthcheck: ตรวจสอบ HTTP `http://127.0.0.1:8000/health` ทุกๆ 30 วินาที
- **Environment Variables**:
  - `WEBEX_BOT_TOKEN`: Token ของ Webex Bot
  - `ROUTER_USER`: Username สำหรับ Login เข้า Router
  - `ROUTER_PASS`: Password สำหรับ Login เข้า Router
  - *ข้อพึงระวัง*: ห้าม Hardcode Token หรือ Password ในซอร์สโค้ด ให้ส่งผ่าน `.env` หรือ Environment เท่านั้น

---

## สรุปแนวข้อสอบปลายภาค (40 Final Exam Review Questions)

ด้านล่างนี้คือสรุปเนื้อหาสำคัญที่เรียบเรียงในรูปแบบ 40 ข้อคำถาม-คำตอบ เพื่อเตรียมตัวสอบข้อสอบปรนัย (MCQ):

### หมวดที่ 1: สถาปัตยกรรมระบบ, Webex และ Webhook (ข้อ 1 - 8)
1. **ถาม**: HTTP 200 จากการยิง `POST /webhook` หมายความว่าอย่างไร?
   - **ตอบ**: หมายถึง Webhook Server ได้รับ event เรียบร้อยแล้ว ยังไม่ใช่ผลลัพธ์การทำงานของคำสั่งบน Router
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
   - **ตอบ**: `GET /health` โดยตอบกลับเป็น `{"status": "ok", "result": "healthy"}`

---

### หมวดที่ 2: การตรวจสอบไฟล์ YAML และกฎ Precedence (ข้อ 9 - 16)
9. **ถาม**: ลำดับความสำคัญในการตรวจสอบความผิดพลาดของไฟล์ YAML (Validation Precedence) เริ่มจากอะไรไปอะไร?
   - **ตอบ**: `invalid_yaml` -> `invalid_version` -> `missing_router` / `invalid_router` -> `missing_method` / `invalid_method` -> `missing_action` / `invalid_action` -> `missing_desired` / `missing_interface` / `missing_interface_name` -> (สำหรับ plan/apply) `missing_ipv4` / `missing_description` / `missing_admin_state` / `invalid_admin_state`
10. **ถาม**: หากไฟล์ YAML ระบุ `version: 2` และไม่มีคีย์ `router` จะได้ข้อผิดพลาดใด?
    - **ตอบ**: `invalid_version` เพราะการตรวจ version อยู่ก่อนการตรวจ router
11. **ถาม**: ค่าของ `version` ที่ถูกต้องในระบบนี้คือค่าใด?
    - **ตอบ**: YAML integer ค่า `1` เท่านั้น (ค่า `"1"`, `1.0`, และ `true` ถือว่าผิดทั้งหมด)
12. **ถาม**: IP Address ของ Router ที่ได้รับอนุญาตให้ใช้งานในระบบมีกี่เบอร์ และมีเบอร์ใดบ้าง?
    - **ตอบ**: 5 เบอร์ ได้แก่ `10.0.29.101` ถึง `10.0.29.105` หากระบุเบอร์อื่นจะได้ `invalid_router`
13. **ถาม**: ฟิลด์ใดใน `desired.interface` ที่จำเป็นต้องมีสำหรับคำสั่ง `status` และ `delete`?
    - **ตอบ**: ต้องการเพียง `name` เท่านั้น (เช่น `Loopback123`)
14. **ถาม**: หากส่งคำขอ `action: status` แต่ใส่ `ipv4: 1.1.1.1` และ `admin_state: invalid-val` มาด้วย จะเกิดอะไรขึ้น?
    - **ตอบ**: ผ่านการตรวจสอบปกติ เพราะระบบจะเพิกเฉย (ignore) ฟิลด์ส่วนเกินเหล่านั้นในคำสั่ง status
15. **ถาม**: ค่าที่ถูกต้องของ `admin_state` มีอะไรบ้าง?
    - **ตอบ**: มี 2 ค่าคือ `"up"` และ `"down"` เท่านั้น
16. **ถาม**: ผลลัพธ์เมื่อไฟล์ YAML ผ่านการตรวจสอบใน Part 1 มีรูปแบบอย่างไร?
    - **ตอบ**: `{"status": "ok", "result": "accepted"}`

---

### หมวดที่ 3: การวางแผนและการเปรียบเทียบ Desired State vs Current State (ข้อ 17 - 24)
17. **ถาม**: Managed Fields ที่ฟังก์ชัน `build_plan()` ใช้เปรียบเทียบมีฟิลด์ใดบ้าง?
    - **ตอบ**: มี 3 ฟิลด์เท่านั้น คือ `ipv4`, `description`, และ `admin_state`
18. **ถาม**: ฟิลด์ `name` สามารถปรากฏใน dictionary `changes` ของผลลัพธ์การ plan ได้หรือไม่?
    - **ตอบ**: **ไม่ได้เด็ดขาด** เพราะ `name` เป็น Identifier ที่ใช้ระบุตัวตนของ interface
19. **ถาม**: กรณีใดที่ `build_plan()` จะตอบ `operation: "create"`?
    - **ตอบ**: เมื่อ `current_interface is None` (ยังไม่มี interface บน router)
20. **ถาม**: โครงสร้างของ `changes` ในกรณี `create` มีลักษณะเด่นอย่างไร?
    - **ตอบ**: มีครบทั้ง 3 managed fields และมีเฉพาะคีย์ `"to"` เท่านั้น (ไม่มี `"from"`)
21. **ถาม**: กรณีใดที่ `build_plan()` จะตอบ `operation: "update"`?
    - **ตอบ**: เมื่อมี interface อยู่แล้ว แต่มี managed field อย่างน้อย 1 ฟิลด์ที่มีค่าต่างจาก desired state
22. **ถาม**: โครงสร้างของ `changes` ในกรณี `update` มีลักษณะเด่นอย่างไร?
    - **ตอบ**: มีเฉพาะฟิลด์ที่ค่าเปลี่ยนแปลง โดยแสดงทั้งค่าเดิม (`"from"`) และค่าใหม่ (`"to"`)
23. **ถาม**: กรณีใดที่ `build_plan()` จะตอบ `operation: "no_change"` และ `changes` เป็นอย่างไร?
    - **ตอบ**: เมื่อค่าของทั้ง 3 ฟิลด์ตรงกันทั้งหมด และ `changes` จะเป็น dict ว่าง `{}`
24. **ถาม**: คำสั่ง `action: delete` มีการเรียกใช้งานฟังก์ชัน `build_plan()` ใน Part 2 หรือไม่?
    - **ตอบ**: **ไม่มี** การลบ interface จัดการแยกต่างหากใน Part 3 โดยตรง

---

### หมวดที่ 4: Network Automation Backends, Protocols และ Data Models (ข้อ 25 - 32)
25. **ถาม**: จับคู่ Method กับ Action ที่ระบบรองรับได้อย่างถูกต้องอย่างไร?
    - **ตอบ**:
      - `restconf`: `status`, `plan`, `apply`
      - `netconf`: `status`, `plan`, `apply`
      - `ansible`: `apply`
      - `netmiko-textfsm`: `status`, `delete`
26. **ถาม**: หากส่ง `method: restconf` ร่วมกับ `action: delete` จะได้รับผลลัพธ์ใด?
    - **ตอบ**: `{"status": "error", "result": "invalid_action"}`
27. **ถาม**: Backend ใดเป็น backend เดียวที่รองรับการ `delete` interface?
    - **ตอบ**: `netmiko-textfsm`
28. **ถาม**: YANG Data Model ใดที่ใช้สำหรับอ่านสถานะ (Status / Read) ใน RESTCONF และ NETCONF?
    - **ตอบ**: Vendor-Neutral Model ได้แก่ `ietf-interfaces` และ `ietf-ip`
29. **ถาม**: YANG Data Model ใดที่ใช้สำหรับเขียนคอนฟิก (Apply / Write) ใน RESTCONF และ NETCONF?
    - **ตอบ**: Vendor-Specific Native Model ได้แก่ `Cisco-IOS-XE-native`
30. **ถาม**: เพราะเหตุใด RESTCONF จึงใช้ HTTP Method `PUT` ในการ `apply` interface แทนที่จะใช้ `POST` หรือ `PATCH`?
    - **ตอบ**: เพื่อแทนที่ (Replace) ทรัพยากรเดิมทั้งหมดแบบ Idempotent ป้องกันการเกิด Secondary IP คั่งค้าง
31. **ถาม**: ใน RESTCONF และ NETCONF หากต้องการให้ interface มีสถานะ `admin_state: up` จะต้องส่งคอนฟิกอย่างไร?
    - **ตอบ**: ต้อง **ละเว้น (omit)** แท็ก `<shutdown/>` หรือคีย์ `"shutdown"` ออกไปจากคอนฟิก
32. **ถาม**: ใน NETCONF คำสั่งที่ใช้ในการแทนที่คอนฟิก Loopback ทั้งก้อนคืออะไร?
    - **ตอบ**: คำสั่ง `<edit-config>` ส่งไปยัง target `<running>` โดยใส่ attribute `nc:operation="replace"` ที่แท็ก `<Loopback>`

---

### หมวดที่ 5: Ansible, Netmiko, การทดสอบ และเกณฑ์การตรวจ (ข้อ 33 - 40)
33. **ถาม**: ใน Ansible Playbook เหตุใดโมดูล `cisco.ios.ios_config` จึงต้องใส่ `defaults: true`?
    - **ตอบ**: เพื่อให้สามารถเปรียบเทียบกับค่า Default ของ Cisco IOS ได้ (เช่น `no shutdown`) ทำให้การรันซ้ำมีความเป็น Idempotent และรายงาน `changed=0`
34. **ถาม**: Netmiko ทำการอ่านสถานะของ interface ด้วยคำสั่ง CLI ใดบ้าง?
    - **ตอบ**: `show ip interface <name>` และ `show interfaces description`
35. **ถาม**: เหตุใด Netmiko จึงต้องมีตรรกะการแปลงชื่อย่อ (Abbreviation Normalization)?
    - **ตอบ**: เพราะ Cisco IOS มักย่อชื่อในคำสั่ง `show interfaces description` เช่น `Loopback123` จะถูกย่อเป็น `Lo123`
36. **ถาม**: เมื่อทำการลบ interface ที่ไม่มีอยู่แล้วบน Router (Delete ซ้ำ) ระบบจะตอบกลับอย่างไร?
    - **ตอบ**: `{"status": "ok", "result": "not_found", "interface": null}` (ถือเป็นการทำงานที่สำเร็จแบบ Idempotent ไม่ใช่ error)
37. **ถาม**: รหัสข้อผิดพลาดระดับ Backend (Backend Errors) มีกี่ประเภท และอะไรบ้าง?
    - **ตอบ**: มี 3 ประเภท คือ `authentication_failed`, `connection_failed`, และ `backend_failed`
38. **ถาม**: การสอบ Take-home มีคะแนนรวมเท่าใด แบ่งเป็นส่วนใดบ้าง?
    - **ตอบ**: รวม 20 คะแนน แบ่งเป็น คะแนน CI 10 คะแนน (Public + Hidden tests 145 ข้อ และ Docker build) และ คะแนน Live Test 10 คะแนน (สุ่มตรวจ 20 กรณี)
39. **ถาม**: นักศึกษาสามารถส่งตรวจจริงด้วยคำสั่ง `grade` ได้สูงสุดกี่ครั้ง?
    - **ตอบ**: สูงสุดไม่เกิน 10 ครั้ง (ส่วนคำสั่ง `register`, `verify`, `score` ไม่จำกัดจำนวนครั้งและไม่เสียโควตา)
40. **ถาม**: ในขั้นตอน Live Test ช่วง IP ใดที่ถูกสงวนไว้สำหรับระบบตรวจของผู้สอน และห้ามมิให้นักศึกษาใช้ทดลองเอง?
    - **ตอบ**: ช่วง `192.0.2.128/27` (และ Interface ทดสอบจะถูกสร้างบน Router `10.0.29.101`)
