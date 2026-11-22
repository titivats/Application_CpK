# Machine Cpk Capability Reporter

Desktop application for entering repeatability measurements across dynamic axis tabs, calculating `Cp / Cpk / Pp / Ppk`, previewing capability charts, and exporting a customer-ready PDF report.

## เปิดใช้งานบน Windows

เปิด **`dist\MachineCpkReporter.exe`** เพื่อใช้งานจริงหรือกด **Load Demo** เพื่อทดลอง เมื่อส่งออก PDF ให้เลือกโฟลเดอร์เก็บรายงานของงานนั้น

## กรอกและนำเข้าค่าวัดจาก Excel

1. ตั้งชื่อแท็บแกนตามงาน แล้วไปที่ **Report Info → Download Excel Template** เพื่อบันทึกไฟล์ `.xlsx` สำหรับแกนเหล่านั้น
2. ที่ชีต **Measurements** กรอกตัวเลขหน่วย mm แกนละ 30 ค่า เรียงตามลำดับ Trial 1–30 หากคัดลอกจากสูตร ให้ใช้ Paste Values
3. หากต้องการนำเข้าสเปกด้วย ให้กรอก **LSL** และ **USL** ในชีต **Specifications** ของแกนนั้น โดยเว้น **Target** ได้ และ **Required Cpk** ที่เว้นว่างจะใช้ 1.33 หากเว้นทั้งสี่ช่อง แอปจะใช้สเปกที่กรอกไว้ในแท็บแกน
4. บันทึก Excel แล้วกด **Report Info → Import Filled Template** ระบบตรวจทุกแกนก่อนนำเข้า จากนั้นกด **Calculate Preview** และ **Export PDF**

สำหรับไฟล์ Excel รูปแบบเดิม ใช้ **Browse Excel → Load Range to Table** ในแท็บแกนได้ตามปกติ

| ตำแหน่งในโปรเจกต์ | หน้าที่ |
|---|---|
| `dist/` | โปรแกรม Windows ที่สร้างเสร็จแล้ว |
| `run_cpk_app.bat`, `main.py`, `desktop_main.py` | เปิดโปรแกรมจากซอร์สและเตรียมระบบกราฟกับ Tkinter |
| `cpk_ui.py`, `cpk_desktop/` | หน้าจอ การรับค่าวัด และส่วนประกอบของหน้าต่าง |
| `cpk_tool/analysis.py`, `cpk_reporting.py` | คำนวณสถิติ สร้างกราฟ และส่งออก PDF |
| `assets/source/Program.png` | ภาพต้นฉบับสำหรับแก้ไขไอคอน |
| `assets/program_source.ico`, `assets/program_source_256.png` | ไอคอนสำหรับรันและบิลด์ สร้างจากภาพต้นฉบับด้วย `tools/sync_program_icon.py` |
| `build_exe.bat`, `MachineCpkReporter.spec` | สคริปต์บิลด์เรียกใช้การตั้งค่า PyInstaller จากไฟล์ spec |
| `tests/` | ชุดทดสอบการคำนวณ หน้าจอ การนำเข้า Excel และส่งออกรายงาน |
| `requirements.txt`, `venv/` | รายการแพ็กเกจและสภาพแวดล้อม Python ในเครื่อง |
| `build/` | ไฟล์ชั่วคราวที่ PyInstaller สร้างระหว่างบิลด์ |

รันชุดทดสอบจากโฟลเดอร์โปรเจกต์

```bat
venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

## Features

- Enter `30` measurements for each axis
- Add extra axis tabs and rename them for studies such as `X1`, `X2`, `Y1`, `Y2`
- Remove axis tabs that are not needed from the current study
- Set `LSL`, `Target`, `USL`, and required `Cpk`
- Load `30` values manually or query them directly from Excel
- Preview capability charts styled like a Minitab-style report
- Use static preview rendering for smoother scrolling and resize behavior
- Export the acceptance summary, one capability page and one diagnostic page per axis, and all readings in acquisition order. A three-axis study with short notes produces eight pages.
- Enter dimensions in millimetres. The capability page includes Cpm when a target and measurable variation are available, plus observed and normal-model overall/within PPM below LSL, above USL and in total.
- An axis passes when all readings are within the inclusive limits and its unrounded Cpk meets its requirement. Constant in-spec readings are marked N/A.

## Run from source

For a fresh Windows checkout, create the environment once from the project root.

```bat
py -3 -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
```

Start the desktop application with `run_cpk_app.bat`.

## Build the Windows application

Run `build_exe.bat` from Windows. It prepares the icons and packages the application using `MachineCpkReporter.spec`. The executable is written to `dist\MachineCpkReporter.exe`.
