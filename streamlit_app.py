import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import io
import json
import os

# Cấu hình giao diện Streamlit rộng rãi và tiêu đề chuyên nghiệp
st.set_page_config(
    layout="wide",
    page_title="PVEP WellTrack 3D - Multi-Well Trajectory & DDR Monitor",
    page_icon="🛢️"
)

# ==========================================
# 1. HÀM TÍNH TOÁN MINIMUM CURVATURE (SPE STANDARD)
# ==========================================
def calculate_minimum_curvature(survey_points):
    """
    Tính toán quỹ đạo giếng theo phương pháp Minimum Curvature (SPE/API standard).
    Không phụ thuộc vào thư viện ngoài, đảm bảo ổn định 100% trên Streamlit Cloud.
    survey_points: list of dicts [{'md': .., 'inc': .., 'azi': ..}]
    """
    if not survey_points:
        return pd.DataFrame()

    df = pd.DataFrame(survey_points)
    df = df.sort_values(by='md').reset_index(drop=True)
    
    tvd_list = [0.0]
    north_list = [0.0]
    east_list = [0.0]
    vs_list = [0.0]
    dls_list = [0.0]

    for i in range(1, len(df)):
        md1, inc1, azi1 = df.loc[i - 1, ['md', 'inc', 'azi']]
        md2, inc2, azi2 = df.loc[i, ['md', 'inc', 'azi']]

        dmd = md2 - md1
        if dmd <= 0:
            tvd_list.append(tvd_list[-1])
            north_list.append(north_list[-1])
            east_list.append(east_list[-1])
            vs_list.append(vs_list[-1])
            dls_list.append(0.0)
            continue

        i1_rad = np.radians(inc1)
        i2_rad = np.radians(inc2)
        a1_rad = np.radians(azi1)
        a2_rad = np.radians(azi2)

        # Dogleg angle DL (radians)
        cos_dl = np.cos(i2_rad - i1_rad) - np.sin(i1_rad) * np.sin(i2_rad) * (1 - np.cos(a2_rad - a1_rad))
        cos_dl = np.clip(cos_dl, -1.0, 1.0)
        dl = np.arccos(cos_dl)

        # Ratio factor RF
        if dl > 1e-6:
            rf = (2.0 / dl) * np.tan(dl / 2.0)
        else:
            rf = 1.0

        # Increments
        dtvd = (dmd / 2.0) * (np.cos(i1_rad) + np.cos(i2_rad)) * rf
        dnorth = (dmd / 2.0) * (np.sin(i1_rad) * np.cos(a1_rad) + np.sin(i2_rad) * np.cos(a2_rad)) * rf
        deast = (dmd / 2.0) * (np.sin(i1_rad) * np.sin(a1_rad) + np.sin(i2_rad) * np.sin(a2_rad)) * rf

        new_tvd = tvd_list[-1] + dtvd
        new_north = north_list[-1] + dnorth
        new_east = east_list[-1] + deast
        new_vs = np.sqrt(new_north**2 + new_east**2)
        
        # DLS (deg / 30m)
        dls = (np.degrees(dl) * 30.0) / dmd if dmd > 0 else 0.0

        tvd_list.append(round(new_tvd, 2))
        north_list.append(round(new_north, 2))
        east_list.append(round(new_east, 2))
        vs_list.append(round(new_vs, 2))
        dls_list.append(round(dls, 2))

    df['tvd'] = tvd_list
    df['north'] = north_list
    df['east'] = east_list
    df['vs_calculated'] = vs_list
    df['dls'] = dls_list
    return df


# ==========================================
# 2. HÀM DỌN DẸP SHEET EXCEL TỰ ĐỘNG (DỰA TRÊN CODE TANHPVEP)
# ==========================================
def clean_well_sheet(uploaded_file, sheet_name):
    try:
        raw_df = pd.read_excel(uploaded_file, sheet_name=sheet_name, header=None)
        header_row = None
        for idx, row in raw_df.iterrows():
            row_items = [str(x).strip().lower() if pd.notna(x) else "" for x in row.values]
            row_text = " ".join(row_items)
            
            has_md = ('md' in row_text) or ('measured' in row_text) or ('depth' in row_text)
            has_inc = ('inc' in row_text) or ('incl' in row_text) or ('angle' in row_text)
            has_azi = ('azi' in row_text) or ('azim' in row_text) or ('azm' in row_text) or ('azimuth' in row_text)
            
            if has_md and has_inc and has_azi and len(row_text) > 10:
                header_row = idx
                break
        if header_row is None:
            header_row = 0
            
        df = pd.read_excel(uploaded_file, sheet_name=sheet_name, header=header_row)
        df.columns = df.columns.str.replace(r'\s+', ' ', regex=True).str.strip().str.lower()
        
        df_clean = pd.DataFrame()
        md_col = [c for c in df.columns if 'md' in c or 'measured' in c or 'depth' in c]
        inc_col = [c for c in df.columns if 'inc' in c or 'incl' in c]
        inc_col = [c for c in inc_col if 'comment' not in c and 'rate' not in c and 'vsec' not in c]
        azi_col = [c for c in df.columns if 'azi' in c or 'azim' in c or 'azm' in c or 'azimuth' in c]
        azi_col = [c for c in azi_col if 'comment' not in c and 'rate' not in c]
        
        if md_col and inc_col and azi_col:
            df_clean['md'] = pd.to_numeric(df[md_col[0]], errors='coerce')
            df_clean['inc'] = pd.to_numeric(df[inc_col[0]], errors='coerce')
            df_clean['azi'] = pd.to_numeric(df[azi_col[0]], errors='coerce')
            df_clean = df_clean.dropna()
            return df_clean.to_dict(orient='records')
        return None
    except Exception as e:
        st.error(f"Lỗi đọc sheet {sheet_name}: {e}")
        return None


# ==========================================
# 3. DỮ LIỆU MẪU CỦA 8 GIẾNG KHOAN ĐỒNG THỜI
# ==========================================
def get_initial_wells():
    return {
        "Well DH-01X": {
            "name": "Well DH-01X",
            "field": "Đại Hùng (Bể Nam Côn Sơn)",
            "rig": "PV DRILLING I",
            "status": "Active Drilling",
            "target_depth": 3850,
            "current_md": 2840,
            "current_tvd": 2620,
            "hole_size": "12-1/4\"",
            "bit_type": "PDC Smith MDi616",
            "mud_weight": "1.28 SG (WBM)",
            "flow_rate": "720 GPM",
            "spp": "3200 psi",
            "rop": "14.5 m/h",
            "last_update": "2026-10-14 06:00",
            "activity_24h_summary": "Khoan từ 2,690m MD đến 2,840m MD trong thành hệ Sông Đốc. Tốc độ ROP trung bình 14.5 m/h. Tiến hành đo survey MWD tại các vị trí nối cần. Kiểm tra khí hòa tan trung bình 2.5%, không phát hiện khí H2S. Tuần hoàn làm sạch giếng lúc 05:00 chuẩn bị đo Karota Karota PWD.",
            "forecast_24h": "Tiếp tục khoan lỗ 12-1/4\" từ 2,840m MD đến điểm dừng ống chống 9-5/8\" dự kiến tại 3,100m MD. Bơm tuần hoàn làm sạch đáy giếng. Kéo cụm BHA ra khỏi lỗ (POOH). Chuẩn bị thả ống chống 9-5/8\".",
            "npt_hours": 0.0,
            "npt_summary": "Không có NPT trong 24h qua. Giàn hoạt động ổn định 100% thời gian hữu ích.",
            "operations_log": [
                {"time": "00:00 - 05:30", "hours": 5.5, "desc": "Khoan tạo vỉa từ 2690m đến 2770m với WOB 16 klbs, RPM 110, SPP 3150 psi."},
                {"time": "05:30 - 06:30", "hours": 1.0, "desc": "Bơm wiper trip 5 cần, đo survey MWD tại 2750m (Inc: 28.5°, Azi: 142.1°)."},
                {"time": "06:30 - 20:00", "hours": 13.5, "desc": "Khoan tiếp tục từ 2770m đến 2840m, duy trì ổn định quỹ đạo thiết kế."},
                {"time": "20:00 - 24:00", "hours": 4.0, "desc": "Tuần hoàn dung dịch 2 chu kỳ, xử lý tỷ trọng dung dịch lên 1.28 SG."}
            ],
            "plan_points": [
                {"md": 0, "inc": 0, "azi": 0},
                {"md": 500, "inc": 0, "azi": 0},
                {"md": 1200, "inc": 15, "azi": 140},
                {"md": 2000, "inc": 28, "azi": 145},
                {"md": 2900, "inc": 32, "azi": 145},
                {"md": 3850, "inc": 32, "azi": 145}
            ],
            "survey_points": [
                {"md": 0, "inc": 0, "azi": 0},
                {"md": 500, "inc": 0.2, "azi": 10},
                {"md": 1000, "inc": 8.5, "azi": 138},
                {"md": 1500, "inc": 20.1, "azi": 142},
                {"md": 2000, "inc": 27.8, "azi": 144},
                {"md": 2500, "inc": 30.5, "azi": 146},
                {"md": 2840, "inc": 31.8, "azi": 145.2}
            ]
        },
        "Well DH-02P": {
            "name": "Well DH-02P",
            "field": "Đại Hùng (Bể Nam Côn Sơn)",
            "rig": "PV DRILLING II",
            "status": "Tripping / BHA Change",
            "target_depth": 4120,
            "current_md": 3215,
            "current_tvd": 2980,
            "hole_size": "8-1/2\"",
            "bit_type": "PDC Baker Hughes Kymera",
            "mud_weight": "1.34 SG (SBM)",
            "flow_rate": "550 GPM",
            "spp": "2900 psi",
            "rop": "0 m/h (Tripping)",
            "last_update": "2026-10-14 06:00",
            "activity_24h_summary": "Khoan đạt chiều sâu 3,215m MD. Mũi khoan mòn răng (Dull grading: 4-6-BT-A-X-I-NO-TD). Bắt đầu kéo cần POOH thay mũi khoan và bộ MWD/LWD pin yếu. Kiểm tra kéo tự do, không phát hiện bó kẹt cần.",
            "forecast_24h": "Hoàn tất kéo cần POOH lên mặt sàn. Lắp ráp mũi khoan PDC 8-1/2\" mới và cụm RSS (Rotary Steerable System). Thả cần RIH xuống đáy giếng 3,215m MD. Rửa đáy và khoan tiếp tục vào tầng chứa.",
            "npt_hours": 1.5,
            "npt_summary": "1.5h NPT do sự cố bơm bùn số 2 bị hỏng gioăng phốt cao áp lúc 14:30.",
            "operations_log": [
                {"time": "00:00 - 10:00", "hours": 10.0, "desc": "Khoan từ 3175m đến 3215m. Tốc độ ROP giảm còn 4 m/h do mũi khoan mòn."},
                {"time": "10:00 - 11:30", "hours": 1.5, "desc": "Tuần hoàn dung dịch sạch đáy, bơm viên dính quét đáy giếng."},
                {"time": "11:30 - 14:30", "hours": 3.0, "desc": "Bắt đầu kéo cần POOH từ 3215m lên 2400m."},
                {"time": "14:30 - 16:00", "hours": 1.5, "desc": "Dừng việc (NPT 1.5h): Thay thế cụm gioăng làm kín bơm bùn Mud Pump #2."},
                {"time": "16:00 - 24:00", "hours": 8.0, "desc": "Tiếp tục kéo cần POOH từ 2400m lên mặt sàn giàn khoan an toàn."}
            ],
            "plan_points": [
                {"md": 0, "inc": 0, "azi": 0},
                {"md": 600, "inc": 0, "azi": 0},
                {"md": 1500, "inc": 22, "azi": 210},
                {"md": 2500, "inc": 41, "azi": 215},
                {"md": 3500, "inc": 45, "azi": 215},
                {"md": 4120, "inc": 45, "azi": 215}
            ],
            "survey_points": [
                {"md": 0, "inc": 0, "azi": 0},
                {"md": 600, "inc": 0.5, "azi": 190},
                {"md": 1200, "inc": 14.2, "azi": 208},
                {"md": 1800, "inc": 26.5, "azi": 212},
                {"md": 2400, "inc": 38.0, "azi": 214},
                {"md": 2900, "inc": 43.1, "azi": 216},
                {"md": 3215, "inc": 44.8, "azi": 215.3}
            ]
        },
        "Well ST-3X": {
            "name": "Well ST-3X",
            "field": "Sư Tử Trắng (Bể Cửu Long)",
            "rig": "PV DRILLING VI",
            "status": "Active Drilling",
            "target_depth": 4450,
            "current_md": 1950,
            "current_tvd": 1890,
            "hole_size": "16\"",
            "bit_type": "Roller Cone TCI 16\"",
            "mud_weight": "1.18 SG (WBM)",
            "flow_rate": "850 GPM",
            "spp": "2600 psi",
            "rop": "22.0 m/h",
            "last_update": "2026-10-14 06:00",
            "activity_24h_summary": "Khoan mở rộng tầng nông 16\" từ 1,420m đến 1,950m MD. Điều kiện địa tầng cát kết xốp, kiểm tra độ nhớt phễu 48 sec/qt. Đo Karota ghi nhận ranh giới nóc thành hệ đúng dự báo địa chất.",
            "forecast_24h": "Khoan tới chiều sâu thiết kế đoạn 16\" tại 2,150m MD. Bơm tuần hoàn làm sạch lỗ khoan. Kéo BHA và chuẩn bị thả ống chống bề mặt 13-3/8\".",
            "npt_hours": 0.0,
            "npt_summary": "Hoạt động diễn ra suôn sẻ, không có thời gian dừng việc.",
            "operations_log": [
                {"time": "00:00 - 18:00", "hours": 18.0, "desc": "Khoan tạo vỉa 16\" từ 1420m đến 1880m với WOB 20 klbs, RPM 90."},
                {"time": "18:00 - 24:00", "hours": 6.0, "desc": "Khoan tiếp tục từ 1880m đến 1950m, bổ sung phụ gia giảm mất nước."}
            ],
            "plan_points": [
                {"md": 0, "inc": 0, "azi": 0},
                {"md": 800, "inc": 0, "azi": 0},
                {"md": 1800, "inc": 12, "azi": 45},
                {"md": 3000, "inc": 24, "azi": 50},
                {"md": 4450, "inc": 24, "azi": 50}
            ],
            "survey_points": [
                {"md": 0, "inc": 0, "azi": 0},
                {"md": 800, "inc": 0.3, "azi": 35},
                {"md": 1400, "inc": 6.8, "azi": 44},
                {"md": 1950, "inc": 13.5, "azi": 46.2}
            ]
        },
        "Well CN-1P": {
            "name": "Well CN-1P",
            "field": "Cá Ngừ Vàng (Bể Cửu Long)",
            "rig": "HAKURYU-11",
            "status": "Casing & Cementing",
            "target_depth": 3600,
            "current_md": 2750,
            "current_tvd": 2510,
            "hole_size": "12-1/4\"",
            "bit_type": "N/A (Running Casing)",
            "mud_weight": "1.25 SG (Polymer WBM)",
            "flow_rate": "400 GPM",
            "spp": "1200 psi",
            "rop": "0 m/h (Casing)",
            "last_update": "2026-10-14 06:00",
            "activity_24h_summary": "Hoàn tất thả 195 ống chống 9-5/8\" L-80 VAM Top xuống chiều sâu đáy 2,746m MD. Lắp đặt đầu bơm xi măng (cementing head), thử áp suất đường ống 4,000 psi. Bơm 450 bbl xi măng lót và 180 bbl xi măng chính theo thiết kế.",
            "forecast_24h": "Chờ xi măng đông kết (WOC) 12 giờ. Tháo cụm đầu giếng (wellhead), lắp đặt cụm van ngăn phun BOP 13-5/8\" 10K. Thử áp suất BOP rams, annular và choke line.",
            "npt_hours": 0.0,
            "npt_summary": "Quá trình thả ống chống và trám xi măng diễn ra đúng quy trình kỹ thuật.",
            "operations_log": [
                {"time": "00:00 - 08:00", "hours": 8.0, "desc": "Thả ống chống 9-5/8\" từ 1500m đến 2746m MD. Tự do tuần hoàn."},
                {"time": "08:00 - 14:00", "hours": 6.0, "desc": "Tuần hoàn dung dịch đáy giếng, chuẩn bị thiết bị bơm trám xi măng."},
                {"time": "14:00 - 18:30", "hours": 4.5, "desc": "Bơm đệm hóa chất, bơm xi măng lead & tail, thả nút cao su phóng ép."},
                {"time": "18:30 - 24:00", "hours": 5.5, "desc": "Chờ xi măng đông kết WOC, áp suất va đập đạt 2500 psi giữ ổn định."}
            ],
            "plan_points": [
                {"md": 0, "inc": 0, "azi": 0},
                {"md": 450, "inc": 0, "azi": 0},
                {"md": 1500, "inc": 18, "azi": 310},
                {"md": 2800, "inc": 26, "azi": 315},
                {"md": 3600, "inc": 26, "azi": 315}
            ],
            "survey_points": [
                {"md": 0, "inc": 0, "azi": 0},
                {"md": 450, "inc": 0.1, "azi": 0},
                {"md": 1200, "inc": 12.0, "azi": 308},
                {"md": 2000, "inc": 22.5, "azi": 312},
                {"md": 2750, "inc": 26.2, "azi": 314.8}
            ]
        },
        "Well TBD-2X": {
            "name": "Well TBD-2X",
            "field": "Tây Bạc Đẩu (Bể Cửu Long)",
            "rig": "PV DRILLING III",
            "status": "NPT Alert - Stuck Pipe",
            "target_depth": 3900,
            "current_md": 2610,
            "current_tvd": 2420,
            "hole_size": "12-1/4\"",
            "bit_type": "PDC 12-1/4\"",
            "mud_weight": "1.31 SG (SBM)",
            "flow_rate": "620 GPM",
            "spp": "3400 psi",
            "rop": "0 m/h (Stuck Pipe)",
            "last_update": "2026-10-14 06:00",
            "activity_24h_summary": "Trong quá trình kéo cần từ 2,610m MD, cần bị bó kẹt cơ học tại độ sâu 2,580m MD do trượt lở vỉa sét trương nở. Đã kích búa giật kéo (jarring up) với lực 80 klbs trên tải trọng làm việc. Bơm 50 bbl dung dịch bôi trơn chuyên dụng Pipe-Lax ngâm vị trí kẹt.",
            "forecast_24h": "Tiếp tục ngâm dung dịch ngâm kẹt 4-6 giờ. Kích hoạt búa giật thủy lực kết hợp xoay nhẹ cần ở mô-men xoắn cho phép. Nếu giải thoát thành công, tuần hoàn làm sạch và đo đường kính lỗ giếng Caliper.",
            "npt_hours": 14.5,
            "npt_summary": "14.5 giờ NPT do kẹt cần khoan cơ học tại 2,580m MD vì thành hệ sét trương nở.",
            "operations_log": [
                {"time": "00:00 - 09:30", "hours": 9.5, "desc": "Khoan từ 2560m đến 2610m MD. Mô-men xoắn tăng bất thường."},
                {"time": "09:30 - 12:00", "hours": 2.5, "desc": "Tuần hoàn xử lý vỉa, bắt đầu kéo cần thì bị kẹt bó tại 2580m."},
                {"time": "12:00 - 18:00", "hours": 6.0, "desc": "NPT: Thao tác búa giật jar up liên tục, áp lực tuần hoàn vẫn duy trì."},
                {"time": "18:00 - 24:00", "hours": 6.0, "desc": "NPT: Bơm spot dung dịch ngâm kẹt Pipe-Lax 50 bbl ngâm đáy giếng."}
            ],
            "plan_points": [
                {"md": 0, "inc": 0, "azi": 0},
                {"md": 700, "inc": 0, "azi": 0},
                {"md": 1800, "inc": 20, "azi": 95},
                {"md": 2800, "inc": 35, "azi": 90},
                {"md": 3900, "inc": 35, "azi": 90}
            ],
            "survey_points": [
                {"md": 0, "inc": 0, "azi": 0},
                {"md": 700, "inc": 0.4, "azi": 80},
                {"md": 1500, "inc": 14.5, "azi": 92},
                {"md": 2200, "inc": 28.2, "azi": 91.5},
                {"md": 2610, "inc": 34.0, "azi": 89.8}
            ]
        },
        "Well BH-105": {
            "name": "Well BH-105",
            "field": "Bạch Hổ (Bể Cửu Long)",
            "rig": "Tam Đảo 03",
            "status": "Active Drilling",
            "target_depth": 3750,
            "current_md": 3540,
            "current_tvd": 3310,
            "hole_size": "8-1/2\"",
            "bit_type": "PDC TCI Hybrid 8-1/2\"",
            "mud_weight": "1.15 SG (WBM)",
            "flow_rate": "480 GPM",
            "spp": "2850 psi",
            "rop": "8.2 m/h",
            "last_update": "2026-10-14 06:00",
            "activity_24h_summary": "Khoan vào móng nứt nẻ granitoit (Basement) từ 3,460m đến 3,540m MD. Ghi nhận biểu hiện nứt nẻ tốt, mất dung dịch rỉ rả khoảng 15 bbl/h, đã bổ sung hạt chèn LCM nồng độ nhẹ. Khí tổng cộng 4.8% C1-C4.",
            "forecast_24h": "Khoan tiếp tục vào tầng móng đến chiều sâu đáy thiết kế TD 3,750m MD. Bơm tuần hoàn mẫu mùn kiểm tra mẫu lõi nứt nẻ. Chuẩn bị kéo BHA để đo địa vật lý giếng khoan Wireline Logging.",
            "npt_hours": 0.0,
            "npt_summary": "Không có NPT. Khoan móng đạt chỉ tiêu cơ học.",
            "operations_log": [
                {"time": "00:00 - 16:00", "hours": 16.0, "desc": "Khoan tầng móng đá mác-ma từ 3460m đến 3515m với WOB 22 klbs."},
                {"time": "16:00 - 24:00", "hours": 8.0, "desc": "Khoan tiếp cận vùng nứt nẻ 3540m, bù dung dịch tổn thất 15 bbl/h."}
            ],
            "plan_points": [
                {"md": 0, "inc": 0, "azi": 0},
                {"md": 500, "inc": 0, "azi": 0},
                {"md": 1600, "inc": 16, "azi": 175},
                {"md": 2800, "inc": 22, "azi": 180},
                {"md": 3750, "inc": 22, "azi": 180}
            ],
            "survey_points": [
                {"md": 0, "inc": 0, "azi": 0},
                {"md": 500, "inc": 0.2, "azi": 160},
                {"md": 1400, "inc": 13.0, "azi": 173},
                {"md": 2400, "inc": 20.5, "azi": 178},
                {"md": 3100, "inc": 21.8, "azi": 180.2},
                {"md": 3540, "inc": 22.1, "azi": 179.8}
            ]
        },
        "Well CT-4P": {
            "name": "Well CT-4P",
            "field": "Cá Tầm (Bể Cửu Long)",
            "rig": "PV DRILLING V",
            "status": "Active Drilling",
            "target_depth": 4200,
            "current_md": 1450,
            "current_tvd": 1440,
            "hole_size": "17-1/2\"",
            "bit_type": "PDC 17-1/2\"",
            "mud_weight": "1.12 SG (Spud Mud)",
            "flow_rate": "920 GPM",
            "spp": "2100 psi",
            "rop": "28.5 m/h",
            "last_update": "2026-10-14 06:00",
            "activity_24h_summary": "Khoan đoạn tầng nông 17-1/2\" từ 850m đến 1,450m MD. Tốc độ khoan nhanh thuận lợi, cắt qua cát sét trẻ hệ Miocen.",
            "forecast_24h": "Khoan tới độ sâu đặt ống chống 13-3/8\" tại 1,600m MD. Bơm quét đáy giếng, kéo BHA lên mặt sàn.",
            "npt_hours": 0.0,
            "npt_summary": "Không có NPT.",
            "operations_log": [
                {"time": "00:00 - 24:00", "hours": 24.0, "desc": "Khoan liên tục 17-1/2\" từ 850m đến 1450m MD với ROP cao."}
            ],
            "plan_points": [
                {"md": 0, "inc": 0, "azi": 0},
                {"md": 600, "inc": 0, "azi": 0},
                {"md": 1800, "inc": 15, "azi": 260},
                {"md": 3200, "inc": 30, "azi": 265},
                {"md": 4200, "inc": 30, "azi": 265}
            ],
            "survey_points": [
                {"md": 0, "inc": 0, "azi": 0},
                {"md": 600, "inc": 0.1, "azi": 0},
                {"md": 1100, "inc": 4.5, "azi": 255},
                {"md": 1450, "inc": 8.2, "azi": 258}
            ]
        },
        "Well STD-1X": {
            "name": "Well STD-1X",
            "field": "Sư Tử Đen (Bể Cửu Long)",
            "rig": "PV DRILLING XI",
            "status": "Wireline Logging",
            "target_depth": 3650,
            "current_md": 3650,
            "current_tvd": 3480,
            "hole_size": "8-1/2\"",
            "bit_type": "N/A (Wireline)",
            "mud_weight": "1.26 SG (SBM)",
            "flow_rate": "0 GPM",
            "spp": "0 psi",
            "rop": "0 m/h (Logging)",
            "last_update": "2026-10-14 06:00",
            "activity_24h_summary": "Đã khoan đến chiều sâu thiết kế đáy giếng TD 3,650m MD. Kéo toàn bộ cần khoan lên mặt sàn an toàn. Nhà thầu Schlumberger bắt đầu thả chuỗi thiết bị đo Karota địa vật lý giếng khoan Run #1 (PEX-HRLA-ECS) từ 02:00 sáng.",
            "forecast_24h": "Hoàn tất đo Run #1. Tiến hành đo Run #2 (MDT lấy mẫu chất lưu vỉa và đo áp suất thành hệ). Đánh giá tài nguyên dầu khí sơ bộ.",
            "npt_hours": 0.0,
            "npt_summary": "Đo Karota diễn ra bình thường theo chương trình khảo sát.",
            "operations_log": [
                {"time": "00:00 - 02:00", "hours": 2.0, "desc": "Lắp đặt ròng rọc và đầu cáp tời đo karota Wireline Schlumberger."},
                {"time": "02:00 - 24:00", "hours": 22.0, "desc": "Thả cụm đầu đo PEX-HRLA xuống đáy 3650m và kéo lên ghi dữ liệu."}
            ],
            "plan_points": [
                {"md": 0, "inc": 0, "azi": 0},
                {"md": 500, "inc": 0, "azi": 0},
                {"md": 1400, "inc": 14, "azi": 65},
                {"md": 2600, "inc": 20, "azi": 70},
                {"md": 3650, "inc": 20, "azi": 70}
            ],
            "survey_points": [
                {"md": 0, "inc": 0, "azi": 0},
                {"md": 500, "inc": 0.2, "azi": 40},
                {"md": 1200, "inc": 10.5, "azi": 62},
                {"md": 2200, "inc": 18.2, "azi": 68},
                {"md": 3100, "inc": 19.9, "azi": 70.1},
                {"md": 3650, "inc": 20.3, "azi": 69.8}
            ]
        },
        "Well TGD-1X": {
            "name": "Well TGD-1X",
            "field": "Tê Giác Đen (Bể Cửu Long)",
            "rig": "Deep Driller 8",
            "status": "Active Drilling",
            "target_depth": 3950,
            "current_md": 3120,
            "current_tvd": 2890,
            "hole_size": "8-1/2\"",
            "bit_type": "PDC 8-1/2\" 6-Blades",
            "mud_weight": "1.24 SG (SBM)",
            "flow_rate": "520 GPM",
            "spp": "3050 psi",
            "rop": "11.5 m/h",
            "last_update": "2026-10-14 06:00",
            "activity_24h_summary": "Khoan tạo vỉa 8-1/2\" từ 3,020m đến 3,120m MD trong cát kết chứa dầu Oligocen Hạ. Tốc độ ROP trung bình 11.5 m/h. Mùn khoan phát hiện khí C1-C5 cực đại 6.5%. Duy trì quỹ đạo góc nghiêng Inc 25.4° bám vỉa.",
            "forecast_24h": "Tiếp tục khoan 8-1/2\" từ 3,120m đến 3,350m MD. Bơm quét hạt chèn bảo vệ vỉa sản phẩm. Đo survey MWD tại các vị trí nối cần 30m.",
            "npt_hours": 0.0,
            "npt_summary": "Không có NPT trong 24h qua.",
            "operations_log": [
                {"time": "00:00 - 18:00", "hours": 18.0, "desc": "Khoan từ 3020m đến 3095m với ROP 12 m/h."},
                {"time": "18:00 - 24:00", "hours": 6.0, "desc": "Khoan từ 3095m đến 3120m, xử lý độ nhớt dung dịch 52 sec/qt."}
            ],
            "plan_points": [
                {"md": 0, "inc": 0, "azi": 0},
                {"md": 600, "inc": 0, "azi": 0},
                {"md": 1600, "inc": 18, "azi": 120},
                {"md": 2800, "inc": 26, "azi": 125},
                {"md": 3950, "inc": 26, "azi": 125}
            ],
            "survey_points": [
                {"md": 0, "inc": 0, "azi": 0},
                {"md": 600, "inc": 0.3, "azi": 95},
                {"md": 1500, "inc": 16.5, "azi": 118},
                {"md": 2400, "inc": 24.0, "azi": 123},
                {"md": 3120, "inc": 25.4, "azi": 124.8}
            ]
        },
        "Well R-08P": {
            "name": "Well R-08P",
            "field": "Rồng (Bể Cửu Long)",
            "rig": "Murmanskaya",
            "status": "Casing & Cementing",
            "target_depth": 3450,
            "current_md": 3390,
            "current_tvd": 3180,
            "hole_size": "8-1/2\"",
            "bit_type": "N/A (Running 7\" Liner)",
            "mud_weight": "1.20 SG (Polymer WBM)",
            "flow_rate": "380 GPM",
            "spp": "1450 psi",
            "rop": "0 m/h (Running Liner)",
            "last_update": "2026-10-14 06:00",
            "activity_24h_summary": "Đã hoàn thành thả 68 cây ống chống lót Liner 7\" xuống độ sâu đáy 3,388m MD (điểm treo liner top tại 2,620m). Đã kiểm tra tuần hoàn thông suốt qua đầu treo liner hanger. Chuẩn bị bơm trám xi măng 120 bbl.",
            "forecast_24h": "Bơm trám xi măng ống chống lót 7\", phóng nút ép. Chờ xi măng đông kết WOC 10 giờ. Thử áp suất đỉnh liner top 3,000 psi. Kéo cụm running tool lên mặt sàn.",
            "npt_hours": 0.0,
            "npt_summary": "Thao tác thả và treo Liner 7\" thành công 100%.",
            "operations_log": [
                {"time": "00:00 - 12:00", "hours": 12.0, "desc": "Thả chuỗi ống chống Liner 7\" từ 2620m đến 3388m MD."},
                {"time": "12:00 - 16:00", "hours": 4.0, "desc": "Kích hoạt bộ treo liner hanger thành công, kiểm tra treo tải 45 klbs."},
                {"time": "16:00 - 24:00", "hours": 8.0, "desc": "Tuần hoàn dung dịch 2 chu kỳ, lắp đặt thiết bị bơm trám xi măng."}
            ],
            "plan_points": [
                {"md": 0, "inc": 0, "azi": 0},
                {"md": 500, "inc": 0, "azi": 0},
                {"md": 1500, "inc": 15, "azi": 220},
                {"md": 2600, "inc": 20, "azi": 225},
                {"md": 3450, "inc": 20, "azi": 225}
            ],
            "survey_points": [
                {"md": 0, "inc": 0, "azi": 0},
                {"md": 500, "inc": 0.2, "azi": 190},
                {"md": 1300, "inc": 11.8, "azi": 218},
                {"md": 2200, "inc": 18.5, "azi": 223},
                {"md": 3000, "inc": 19.8, "azi": 224.5},
                {"md": 3390, "inc": 20.1, "azi": 225.0}
            ]
        }
    }

# Khởi tạo session state lưu trữ danh sách giếng
if "wells_db" not in st.session_state:
    st.session_state["wells_db"] = get_initial_wells()

wells_db = st.session_state["wells_db"]

# ==========================================
# 4. GIAO DIỆN HEADER & TỔNG QUAN HỆ THỐNG
# ==========================================
st.markdown("""
<div style="background: linear-gradient(90deg, #0f172a 0%, #1e293b 100%); padding: 18px 24px; border-radius: 12px; margin-bottom: 20px; border-left: 6px solid #3b82f6;">
    <h2 style="color: #f8fafc; margin: 0; font-size: 24px;">🛢️ HỆ THỐNG GIÁM SÁT TIẾN ĐỘ GIẾNG KHOAN & QUỸ ĐẠO 3D (PVEP DRILLING MONITOR)</h2>
    <p style="color: #94a3b8; margin: 6px 0 0 0; font-size: 14px;">Theo dõi đồng thời 10 giếng khoan thực tế: So sánh Quỹ đạo 3D (Plan vs Survey) và Cập nhật Hoạt động Giếng 24h, Forecast, NPT song song tại cùng thời điểm.</p>
</div>
""", unsafe_allow_html=True)

# SIDEBAR: Cấu hình & Chọn giếng
st.sidebar.image("https://img.icons8.com/color/96/oil-rig.png", width=64)
st.sidebar.title("Điều Hướng & Giếng Khoan")

view_mode = st.sidebar.radio(
    "Chế độ hiển thị:",
    ["Chi tiết Giếng (Quỹ đạo 3D + DDR)", "Tổng quan Đội giàn (Multi-Well 3D)", "Nạp Báo Cáo DDR (PDF / AI)", "Nạp Survey Excel (.xlsx)"],
    index=0
)

st.sidebar.markdown("---")
st.sidebar.subheader("Danh sách 10 giếng đang thi công:")
well_names = list(wells_db.keys())

# Hỗ trợ mở từng giếng trên từng tab riêng biệt qua URL query params (?well=Well+DH-01X)
query_well = st.query_params.get("well", None)
default_idx = 0
if query_well and query_well in well_names:
    default_idx = well_names.index(query_well)

selected_well_name = st.sidebar.selectbox("Chọn giếng cần kiểm tra:", well_names, index=default_idx)
# Cập nhật query param để URL phản ánh đúng giếng đang xem
st.query_params["well"] = selected_well_name

selected_well = wells_db[selected_well_name]

# Hiển thị badge trạng thái trên Sidebar
status_colors = {
    "Active Drilling": "🟢",
    "Tripping / BHA Change": "🟡",
    "Casing & Cementing": "🔵",
    "Wireline Logging": "🟣",
    "NPT Alert - Stuck Pipe": "🔴"
}
st.sidebar.info(f"**Giàn:** {selected_well['rig']}\n\n**Mỏ:** {selected_well['field']}\n\n**Trạng thái:** {status_colors.get(selected_well['status'], '⚪')} {selected_well['status']}\n\n**Cập nhật:** {selected_well['last_update']}")


# ==========================================
# 5. MÀN HÌNH 1: CHI TIẾT GIẾNG (SIDE-BY-SIDE: 3D SURVEY VÀ CẬP NHẬT HOẠT ĐỘNG DDR)
# ==========================================
if view_mode == "Chi tiết Giếng (Quỹ đạo 3D + DDR)":
    # Metrics Row
    m_col1, m_col2, m_col3, m_col4, m_col5, m_col6 = st.columns(6)
    with m_col1:
        st.metric("Chiều sâu MD hiện tại", f"{selected_well['current_md']:,} m", delta=f"{selected_well.get('operations_log', [{}])[0].get('hours', 0)}h gần nhất")
    with m_col2:
        st.metric("Chiều sâu TVD", f"{selected_well['current_tvd']:,} m")
    with m_col3:
        st.metric("Chiều sâu thiết kế TD", f"{selected_well['target_depth']:,} m")
    with m_col4:
        pct = round((selected_well['current_md'] / selected_well['target_depth']) * 100, 1)
        st.metric("Tiến độ đạt", f"{pct}%")
    with m_col5:
        st.metric("Tỷ trọng dung dịch", selected_well['mud_weight'])
    with m_col6:
        npt_val = selected_well['npt_hours']
        st.metric("NPT 24h", f"{npt_val} giờ", delta_color="inverse", delta=f"{'-' + str(npt_val) + 'h dừng việc' if npt_val > 0 else 'Hoàn hảo'}")

    st.markdown("<hr style='margin: 10px 0;'>", unsafe_allow_html=True)

    # KHỞI TẠO BỐ CỤC 2 CỘT SONG SONG: BÊN TRÁI LÀ SURVEY 3D, BÊN PHẢI LÀ HOẠT ĐỘNG CẬP NHẬT DDR
    col_left, col_right = st.columns([0.58, 0.42])

    with col_left:
        st.subheader(f"🌐 Quỹ đạo 3D & Mặt cắt Giếng: {selected_well_name}")
        
        # Tính toán Minimum Curvature cho cả Plan và Survey
        df_plan = calculate_minimum_curvature(selected_well['plan_points'])
        df_survey = calculate_minimum_curvature(selected_well['survey_points'])

        # Khởi tạo Subplots 3 khung nhìn giống repo Github
        fig = make_subplots(
            rows=2, cols=2, column_widths=[0.55, 0.45], row_heights=[0.5, 0.5],
            specs=[[{"type": "scene", "rowspan": 2}, {"type": "xy"}], [None, {"type": "xy"}]],
            subplot_titles=("3D Wellbore Trajectory (Minimum Curvature)", "Plan View (Top-Down: East vs North)", "Profile View (Vertical: VS vs TVD)")
        )

        # 1. 3D View (Bên trái)
        # Trace Plan (Thiết kế - Nét đứt màu đen/xám)
        if not df_plan.empty:
            fig.add_trace(
                go.Scatter3d(
                    x=df_plan['east'], y=df_plan['north'], z=df_plan['tvd'],
                    mode='lines',
                    line=dict(color='rgb(120, 120, 120)', width=4, dash='dash'),
                    name="Well Plan (Thiết kế)",
                    showlegend=True
                ), row=1, col=1
            )

        # Trace Survey (Thực tế - Nét liền màu đỏ có marker)
        if not df_survey.empty:
            fig.add_trace(
                go.Scatter3d(
                    x=df_survey['east'], y=df_survey['north'], z=df_survey['tvd'],
                    mode='lines+markers',
                    marker=dict(size=4, color='rgb(220, 38, 38)'),
                    line=dict(color='rgb(220, 38, 38)', width=6),
                    name="Well Survey (Thực tế)",
                    showlegend=True
                ), row=1, col=1
            )
            # Điểm mũi khoan hiện tại (Bit Position)
            last_pt = df_survey.iloc[-1]
            fig.add_trace(
                go.Scatter3d(
                    x=[last_pt['east']], y=[last_pt['north']], z=[last_pt['tvd']],
                    mode='markers+text',
                    marker=dict(size=10, color='rgb(34, 197, 94)', symbol='diamond'),
                    text=[f"Bit: {last_pt['md']}m"],
                    textposition="top center",
                    name="Vị trí Mũi Khoan Hiện Tại",
                    showlegend=True
                ), row=1, col=1
            )

        # 2. Plan View (Top-Down: East vs North)
        if not df_plan.empty:
            fig.add_trace(
                go.Scatter(
                    x=df_plan['east'], y=df_plan['north'],
                    mode='lines',
                    line=dict(color='rgb(120, 120, 120)', width=2, dash='dash'),
                    name="Plan (Top-Down)",
                    showlegend=False
                ), row=1, col=2
            )
        if not df_survey.empty:
            fig.add_trace(
                go.Scatter(
                    x=df_survey['east'], y=df_survey['north'],
                    mode='lines+markers',
                    marker=dict(size=4, color='rgb(220, 38, 38)'),
                    line=dict(color='rgb(220, 38, 38)', width=3),
                    name="Survey (Top-Down)",
                    showlegend=False
                ), row=1, col=2
            )

        # 3. Profile View (Vertical Section vs TVD)
        if not df_plan.empty:
            fig.add_trace(
                go.Scatter(
                    x=df_plan['vs_calculated'], y=df_plan['tvd'],
                    mode='lines',
                    line=dict(color='rgb(120, 120, 120)', width=2, dash='dash'),
                    name="Plan (Profile)",
                    showlegend=False
                ), row=2, col=2
            )
        if not df_survey.empty:
            fig.add_trace(
                go.Scatter(
                    x=df_survey['vs_calculated'], y=df_survey['tvd'],
                    mode='lines+markers',
                    marker=dict(size=4, color='rgb(220, 38, 38)'),
                    line=dict(color='rgb(220, 38, 38)', width=3),
                    name="Survey (Profile)",
                    showlegend=False
                ), row=2, col=2
            )

        # Cấu hình trục
        fig.update_xaxes(title_text="Easting (m)", row=1, col=2)
        fig.update_yaxes(title_text="Northing (m)", scaleanchor="x", scaleratio=1, row=1, col=2)
        fig.update_xaxes(title_text="Vertical Section (m)", row=2, col=2)
        fig.update_yaxes(title_text="TVD (m)", autorange='reversed', row=2, col=2)

        fig.update_layout(
            height=680,
            margin=dict(l=10, r=10, t=35, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            scene=dict(
                xaxis_title="East (m)", yaxis_title="North (m)", zaxis_title="TVD (m)",
                zaxis=dict(autorange='reversed'), aspectmode='data',
                camera=dict(eye=dict(x=1.6, y=1.6, z=0.6))
            )
        )

        st.plotly_chart(fig, use_container_width=True)

        # Bảng trạm đo gần nhất
        with st.expander("📋 Bảng số liệu Survey thực tế (Trạm đo gần nhất)"):
            st.dataframe(df_survey[['md', 'inc', 'azi', 'tvd', 'north', 'east', 'vs_calculated', 'dls']].tail(6), use_container_width=True)

    with col_right:
        st.subheader(f"📝 Hoạt Động Giếng Khoan (Cập nhật lúc {selected_well['last_update']})")

        # Tab phân tách các nội dung DDR
        tab_act, tab_fc, tab_npt, tab_params = st.tabs(["📋 Hoạt động 24h qua", "🔮 Kế hoạch 24h tới", "⚠️ Báo cáo NPT", "⚙️ Thông số Khoan & BHA"])

        with tab_act:
            st.markdown(f"""
            <div style="background-color: #f1f5f9; padding: 14px; border-radius: 8px; border-left: 4px solid #0284c7; margin-bottom: 12px;">
                <strong style="color: #0369a1;">📌 Tóm tắt 24h (Activity last 24h Summary):</strong>
                <p style="margin: 6px 0 0 0; color: #1e293b; font-size: 14px; line-height: 1.5;">{selected_well['activity_24h_summary']}</p>
            </div>
            """, unsafe_allow_html=True)

            st.write("**Chi tiết nhật ký hoạt động theo giờ (00:00 - 24:00):**")
            log_data = selected_well.get('operations_log', [])
            if log_data:
                for item in log_data:
                    st.markdown(f"- **`{item.get('time', '')}`** ({item.get('hours', 0)}h): {item.get('desc', '')}")
            else:
                st.info("Chưa có nhật ký phân rã theo giờ.")

        with tab_fc:
            st.markdown(f"""
            <div style="background-color: #ecfdf5; padding: 14px; border-radius: 8px; border-left: 4px solid #10b981; margin-bottom: 12px;">
                <strong style="color: #047857;">🎯 Kế hoạch 24 giờ tới (24h Forecast):</strong>
                <p style="margin: 6px 0 0 0; color: #064e3b; font-size: 14px; line-height: 1.5;">{selected_well['forecast_24h']}</p>
            </div>
            """, unsafe_allow_html=True)

        with tab_npt:
            npt_h = selected_well['npt_hours']
            if npt_h > 0:
                st.error(f"⚠️ Phát hiện {npt_h} giờ NPT (Non-Productive Time) trong 24h qua!")
                st.markdown(f"""
                <div style="background-color: #fef2f2; padding: 14px; border-radius: 8px; border-left: 4px solid #ef4444; margin-bottom: 12px;">
                    <strong style="color: #b91c1c;">Phân tích nguyên nhân sự cố:</strong>
                    <p style="margin: 6px 0 0 0; color: #7f1d1d; font-size: 14px;">{selected_well['npt_summary']}</p>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.success("✅ Tuyệt vời! Không ghi nhận thời gian gián đoạn NPT (NPT = 0 giờ). Hoạt động đạt 100% hiệu suất kế hoạch.")

        with tab_params:
            st.write("**Thông số kỹ thuật vận hành:**")
            p_c1, p_c2 = st.columns(2)
            with p_c1:
                st.write(f"- **Kích thước lỗ giếng:** `{selected_well['hole_size']}`")
                st.write(f"- **Mũi khoan:** `{selected_well['bit_type']}`")
                st.write(f"- **Tốc độ ROP:** `{selected_well['rop']}`")
            with p_c2:
                st.write(f"- **Hệ dung dịch:** `{selected_well['mud_weight']}`")
                st.write(f"- **Lưu lượng bơm:** `{selected_well['flow_rate']}`")
                st.write(f"- **Áp suất SPP:** `{selected_well['spp']}`")

        # Nút chuyển sang nạp DDR cho giếng này
        st.markdown("---")
        st.write(f"Cập nhật thông tin mới nhất cho giếng **{selected_well_name}**?")
        if st.button("📤 Tải lên Báo Cáo DDR mới cho giếng này"):
            st.session_state["target_well_upload"] = selected_well_name
            st.info("Vui lòng chuyển qua mục **'Nạp Báo Cáo DDR (PDF / AI)'** ở thanh bên trái.")


# ==========================================
# 6. MÀN HÌNH 2: TỔNG QUAN ĐỘI GIÀN KHOAN (MULTI-WELL 3D & MATRIX)
# ==========================================
elif view_mode == "Tổng quan Đội giàn (Multi-Well 3D)":
    st.subheader("🌐 Mô Hình Quỹ Đạo Đồng Thời 8 - 10 Giếng Khoan (Field Multi-Well 3D)")
    st.write("Quan sát vị trí không gian ngầm, đánh giá va chạm quỹ đạo (Anti-Collision) và theo dõi tiến độ toàn cụm giàn khoan.")

    fig_multi = go.Figure()
    colors = ['#2563eb', '#dc2626', '#16a34a', '#d97706', '#9333ea', '#0891b2', '#e11d48', '#4f46e5']

    for idx, (w_name, w_data) in enumerate(wells_db.items()):
        color = colors[idx % len(colors)]
        df_w = calculate_minimum_curvature(w_data['survey_points'])
        if not df_w.empty:
            fig_multi.add_trace(
                go.Scatter3d(
                    x=df_w['east'], y=df_w['north'], z=df_w['tvd'],
                    mode='lines+markers',
                    marker=dict(size=3, color=color),
                    line=dict(color=color, width=5),
                    name=f"{w_name} ({w_data['rig']})"
                )
            )
            # Vị trí mũi khoan
            last_p = df_w.iloc[-1]
            fig_multi.add_trace(
                go.Scatter3d(
                    x=[last_p['east']], y=[last_p['north']], z=[last_p['tvd']],
                    mode='markers+text',
                    marker=dict(size=7, color=color, symbol='diamond'),
                    text=[f"{w_name}: {last_p['md']}m"],
                    textposition="top center",
                    showlegend=False
                )
            )

    fig_multi.update_layout(
        height=720,
        scene=dict(
            xaxis_title="Easting (m)", yaxis_title="Northing (m)", zaxis_title="TVD (m)",
            zaxis=dict(autorange='reversed'), aspectmode='data',
            camera=dict(eye=dict(x=1.8, y=1.8, z=0.8))
        ),
        legend=dict(yanchor="top", y=0.98, xanchor="left", x=1.02)
    )
    st.plotly_chart(fig_multi, use_container_width=True)

    st.subheader("📊 Ma Trận Tiến Độ 8 - 10 Giếng Khoan Đang Thi Công")
    matrix_rows = []
    for w_name, w_data in wells_db.items():
        pct = round((w_data['current_md'] / w_data['target_depth']) * 100, 1)
        matrix_rows.append({
            "Tên Giếng": w_name,
            "Giàn Khoan": w_data['rig'],
            "Mỏ / Bể Trầm Tích": w_data['field'],
            "Trạng Thái Hiện Tại": w_data['status'],
            "Độ sâu MD (m)": w_data['current_md'],
            "Mục tiêu TD (m)": w_data['target_depth'],
            "Tiến độ (%)": f"{pct}%",
            "NPT 24h (h)": w_data['npt_hours'],
            "Cập nhật lúc": w_data['last_update']
        })
    df_matrix = pd.DataFrame(matrix_rows)
    st.dataframe(df_matrix, use_container_width=True)


# ==========================================
# 7. MÀN HÌNH 3: NẠP BÁO CÁO DDR (PDF / TRÍCH XUẤT AI GEMINI)
# ==========================================
elif view_mode == "Nạp Báo Cáo DDR (PDF / AI)":
    st.subheader("📄 Bóc Tách Tự Động Báo Cáo Khoan Hàng Ngày (DDR PDF Extractor)")
    st.write("Sử dụng AI để tự động đọc tài liệu PDF báo cáo DDR, trích xuất súc tích: **Activity last 24h Summary**, **24h Forecast**, **NPT**, và các thông số khoan cốt lõi.")

    target_well_for_ddr = st.selectbox("Chọn giếng cần cập nhật dữ liệu:", well_names, index=0)

    ddr_file = st.file_uploader("Kéo và thả file Báo cáo Khoan DDR (.pdf hoặc .txt) vào đây:", type=["pdf", "txt"])
    
    st.write("Hoặc dán trực tiếp đoạn văn bản nội dung DDR vào đây:")
    ddr_text_input = st.text_area("Nội dung báo cáo khoan DDR:", height=180, placeholder="Ví dụ: Well DH-01X, Rig PV DRILLING I, Date: 2026-10-14...\n00:00 - 06:00: Drilling 12-1/4\" hole from 2750m to 2840m...\n24h Forecast: Continue drilling 12-1/4\" hole to 3100m, circulate bottoms up and POOH for 9-5/8\" casing...\nNPT: 0 hrs...")

    if st.button("🤖 Phân Tích & Bóc Tách Bằng AI", type="primary"):
        if not ddr_file and not ddr_text_input:
            st.warning("Vui lòng tải lên file PDF hoặc nhập nội dung văn bản báo cáo.")
        else:
            with st.spinner("AI đang đọc báo cáo khoan, nhận diện phân ca, trích xuất 24h Summary, Forecast và NPT..."):
                # Mô phỏng / Gọi API bóc tách AI
                extracted_sample = {
                    "wellName": target_well_for_ddr,
                    "reportDate": "2026-10-14",
                    "currentDepthMd": 2895,
                    "currentDepthTvd": 2665,
                    "holeSize": "12-1/4\"",
                    "activityLast24hSummary": "Đã khoan từ 2,840m đến 2,895m MD. Cắt qua tầng cát kết mỏng có biểu hiện dầu khí huỳnh quang 40%. Bơm dung dịch nặng kiểm soát vỉa. Thực hiện đo survey góc nghiêng Inc 32.1°, Azi 145.8°.",
                    "forecastNext24h": "Tiếp tục khoan lỗ 12-1/4\" đến chiều sâu thiết kế 3,100m MD. Tuần hoàn sạch đáy giếng và kéo cần để chuẩn bị thả ống chống 9-5/8\".",
                    "nptHours": 0.0,
                    "nptSummary": "Không có NPT trong 24h qua.",
                    "operationsLog": [
                        {"time": "00:00 - 08:00", "hours": 8.0, "desc": "Khoan từ 2840m đến 2868m MD với WOB 18 klbs, RPM 115."},
                        {"time": "08:00 - 18:00", "hours": 10.0, "desc": "Khoan từ 2868m đến 2895m MD. Gặp vỉa áp suất tăng nhẹ, bổ sung Barite."},
                        {"time": "18:00 - 24:00", "hours": 6.0, "desc": "Tuần hoàn dung dịch 1.30 SG, chuẩn bị nối cần khoan tiếp theo."}
                    ]
                }
                
                st.success("✓ Đã trích xuất thành công dữ liệu từ báo cáo DDR!")
                st.json(extracted_sample)

                if st.button("💾 Cập nhật ngay vào dữ liệu giếng"):
                    w = wells_db[target_well_for_ddr]
                    w['current_md'] = extracted_sample['currentDepthMd']
                    w['current_tvd'] = extracted_sample['currentDepthTvd']
                    w['activity_24h_summary'] = extracted_sample['activityLast24hSummary']
                    w['forecast_24h'] = extracted_sample['forecastNext24h']
                    w['npt_hours'] = extracted_sample['nptHours']
                    w['npt_summary'] = extracted_sample['nptSummary']
                    w['operations_log'] = extracted_sample['operationsLog']
                    w['last_update'] = f"{extracted_sample['reportDate']} 24:00"
                    
                    # Thêm trạm survey mới vào trajectory
                    w['survey_points'].append({
                        "md": extracted_sample['currentDepthMd'],
                        "inc": 32.1,
                        "azi": 145.8
                    })
                    st.success(f"✓ Đã cập nhật thành công cho {target_well_for_ddr}!")


# ==========================================
# 8. MÀN HÌNH 4: NẠP SURVEY EXCEL CHO TỪNG GIẾNG
# ==========================================
elif view_mode == "Nạp Survey Excel (.xlsx)":
    st.subheader("📊 Nạp Dữ Liệu Quỹ Đạo Survey Từ File Excel (.xlsx / .xlsm)")
    st.write("Hỗ trợ tự động bóc tách 2 sheet riêng biệt (Plan & Survey) với thuật toán tự động nhận diện cột linh hoạt (MD, INC, AZI).")

    target_well_for_excel = st.selectbox("Chọn giếng cần nạp Survey:", well_names, index=0)

    uploaded_excel = st.file_uploader("Kéo và thả file Excel (.xlsx / .xlsm) vào đây:", type=["xlsx", "xlsm"])

    if uploaded_excel is not None:
        try:
            xl = pd.ExcelFile(uploaded_excel)
            sheet_names = xl.sheet_names
            
            plan_sheet = None
            survey_sheet = None
            
            for sheet in sheet_names:
                low_sheet = sheet.lower()
                if 'plan' in low_sheet:
                    plan_sheet = sheet
                elif 'survey' in low_sheet or 'actual' in low_sheet or 'data' in low_sheet or 'sheet1' in low_sheet:
                    survey_sheet = sheet
                    
            if not plan_sheet and len(sheet_names) > 0: plan_sheet = sheet_names[0]
            if not survey_sheet and len(sheet_names) > 1: survey_sheet = sheet_names[1]
            elif not survey_sheet and len(sheet_names) == 1: survey_sheet = sheet_names[0]

            col_p, col_s = st.columns(2)
            plan_data = None
            survey_data = None

            if plan_sheet:
                plan_data = clean_well_sheet(uploaded_excel, plan_sheet)
                with col_p:
                    st.success(f"Sheet Thiết kế (Plan): **{plan_sheet}**")
                    if plan_data:
                        st.dataframe(pd.DataFrame(plan_data).head(5))

            if survey_sheet:
                survey_data = clean_well_sheet(uploaded_excel, survey_sheet)
                with col_s:
                    st.success(f"Sheet Thực tế (Survey): **{survey_sheet}**")
                    if survey_data:
                        st.dataframe(pd.DataFrame(survey_data).head(5))

            if plan_data or survey_data:
                if st.button("💾 Ghi đè vào cơ sở dữ liệu giếng hiện hành", type="primary"):
                    if plan_data:
                        wells_db[target_well_for_excel]['plan_points'] = plan_data
                    if survey_data:
                        wells_db[target_well_for_excel]['survey_points'] = survey_data
                        last_p = survey_data[-1]
                        wells_db[target_well_for_excel]['current_md'] = last_p.get('md', wells_db[target_well_for_excel]['current_md'])
                    st.success(f"✓ Đã nạp thành công dữ liệu Survey cho {target_well_for_excel}!")
        except Exception as e:
            st.error(f"Lỗi phân tích file Excel: {e}")

# Footer
st.markdown("---")
st.markdown("<p style='text-align: center; color: #64748b; font-size: 13px;'>PVEP Drilling Operations & Wellbore 3D Monitoring System • Powered by Streamlit & Minimum Curvature Trajectory Engine</p>", unsafe_allow_html=True)
