import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import io
import json
import os
from google import genai
from google.genai import types

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
# 2. HÀM DỌN DẸP SHEET EXCEL TỰ ĐỘNG
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
# 3. DỮ LIỆU MẪU KHỞI TẠO CỦA CÁC GIẾNG KHOAN
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
                {"md": 0, "inc": 0, "azi": 0}, {"md": 500, "inc": 0, "azi": 0},
                {"md": 1200, "inc": 15, "azi": 140}, {"md": 2000, "inc": 28, "azi": 145},
                {"md": 2900, "inc": 32, "azi": 145}, {"md": 3850, "inc": 32, "azi": 145}
            ],
            "survey_points": [
                {"md": 0, "inc": 0, "azi": 0}, {"md": 500, "inc": 0.2, "azi": 10},
                {"md": 1000, "inc": 8.5, "azi": 138}, {"md": 1500, "inc": 20.1, "azi": 142},
                {"md": 2000, "inc": 27.8, "azi": 144}, {"md": 2500, "inc": 30.5, "azi": 146},
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
            "activity_24h_summary": "Khoan đạt chiều sâu 3,215m MD. Mũi khoan mòn răng. Bắt đầu kéo cần POOH thay mũi khoan và bộ MWD/LWD pin yếu.",
            "forecast_24h": "Hoàn tất kéo cần POOH lên mặt sàn. Lắp ráp mũi khoan PDC 8-1/2\" mới và cụm RSS. Thả cần RIH xuống đáy giếng 3,215m MD.",
            "npt_hours": 1.5,
            "npt_summary": "1.5h NPT do sự cố bơm bùn số 2 bị hỏng gioăng phốt cao áp lúc 14:30.",
            "operations_log": [
                {"time": "00:00 - 10:00", "hours": 10.0, "desc": "Khoan từ 3175m đến 3215m. Tốc độ ROP giảm còn 4 m/h do mũi khoan mòn."},
                {"time": "14:30 - 16:00", "hours": 1.5, "desc": "Dừng việc (NPT 1.5h): Thay thế cụm gioăng làm kín bơm bùn Mud Pump #2."}
            ],
            "plan_points": [
                {"md": 0, "inc": 0, "azi": 0}, {"md": 600, "inc": 0, "azi": 0},
                {"md": 1500, "inc": 22, "azi": 210}, {"md": 2500, "inc": 41, "azi": 215},
                {"md": 4120, "inc": 45, "azi": 215}
            ],
            "survey_points": [
                {"md": 0, "inc": 0, "azi": 0}, {"md": 600, "inc": 0.5, "azi": 190},
                {"md": 1200, "inc": 14.2, "azi": 208}, {"md": 2400, "inc": 38.0, "azi": 214},
                {"md": 3215, "inc": 44.8, "azi": 215.3}
            ]
        }
    }

if "wells_db" not in st.session_state:
    st.session_state["wells_db"] = get_initial_wells()

wells_db = st.session_state["wells_db"]

# ==========================================
# 4. GIAO DIỆN HEADER & TỔNG QUAN HỆ THỐNG
# ==========================================
st.markdown("""
HỆ THỐNG GIÁM SÁT TIẾN ĐỘ GIẾNG KHOAN & QUỸ ĐẠO 3D (PVEP DRILLING MONITOR)
Theo dõi đồng thời các giếng khoan thực tế: So sánh Quỹ đạo 3D (Plan vs Survey) và Cập nhật Hoạt động Giếng 24h song song.

""", unsafe_allow_html=True)
st.sidebar.image("icons8.com", width=64)
st.sidebar.title("Điều Hướng & Giếng Khoan")
view_mode = st.sidebar.radio(
"Chế độ hiển thị:",
["Chi tiết Giếng (Quỹ đạo 3D + DDR)", "Tổng quan Đội giàn (Multi-Well 3D)", "Nạp Báo Cáo DDR (PDF / AI)", "Nạp Survey Excel (.xlsx)"],
index=0
)
well_names = list(wells_db.keys())
query_well = st.query_params.get("well", None)
default_idx = 0
if query_well and query_well in well_names:
default_idx = well_names.index(query_well)
selected_well_name = st.sidebar.selectbox("Chọn giếng cần kiểm tra:", well_names, index=default_idx)
st.query_params["well"] = selected_well_name
selected_well = wells_db[selected_well_name]
status_colors = {"Active Drilling": "🟢", "Tripping / BHA Change": "🟡", "Casing & Cementing": "🔵", "Wireline Logging": "🟣", "NPT Alert - Stuck Pipe": "🔴"}
st.sidebar.info(f"Giàn: {selected_well['rig']}\n\nMỏ: {selected_well['field']}\n\nTrạng thái: {status_colors.get(selected_well['status'], '⚪')} {selected_well['status']}\n\nCập nhật: {selected_well['last_update']}")

==========================================


#5. CHI TIẾT GIẾNG (3D SURVEY + DDR)


==========================================

if view_mode == "Chi tiết Giếng (Quỹ đạo 3D + DDR)":
m_col1, m_col2, m_col3, m_col4, m_col5, m_col6 = st.columns(6)
with m_col1:
st.metric("Chiều sâu MD hiện tại", f"{selected_well['current_md']:,} m")
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
st.metric("NPT 24h", f"{npt_val} giờ")
st.markdown("", unsafe_allow_html=True)
col_left, col_right = st.columns([0.58, 0.42])
with col_left:
st.subheader(f"🌐 Quỹ đạo 3D & Mặt cắt Giếng: {selected_well_name}")
df_plan = calculate_minimum_curvature(selected_well['plan_points'])
df_survey = calculate_minimum_curvature(selected_well['survey_points'])
fig = make_subplots(
rows=2, cols=2, column_widths=[0.55, 0.45], row_heights=[0.5, 0.5],
specs=[[{"type": "scene", "rowspan": 2}, {"type": "xy"}], [None, {"type": "xy"}]],
subplot_titles=("3D Wellbore Trajectory", "Plan View (East vs North)", "Profile View (VS vs TVD)")
)
if not df_plan.empty:
fig.add_trace(go.Scatter3d(x=df_plan['east'], y=df_plan['north'], z=df_plan['tvd'], mode='lines', line=dict(color='gray', width=3, dash='dash'), name="Plan (Thiết kế)"), row=1, col=1)
if not df_survey.empty:
fig.add_trace(go.Scatter3d(x=df_survey['east'], y=df_survey['north'], z=df_survey['tvd'], mode='lines+markers', marker=dict(size=3, color='red'), line=dict(color='red', width=5), name="Survey (Thực tế)"), row=1, col=1)
last_pt = df_survey.iloc[-1]
fig.add_trace(go.Scatter3d(x=[last_pt['east']], y=[last_pt['north']], z=[last_pt['tvd']], mode='markers+text', marker=dict(size=8, color='green', symbol='diamond'), text=[f"Bit: {last_pt['md']}m"], name="Vị trí Mũi Khoan"), row=1, col=1)
if not df_plan.empty:
fig.add_trace(go.Scatter(x=df_plan['east'], y=df_plan['north'], mode='lines', line=dict(color='gray', width=2, dash='dash'), showlegend=False), row=1, col=2)
fig.add_trace(go.Scatter(x=df_plan['vs_calculated'], y=df_plan['tvd'], mode='lines', line=dict(color='gray', width=2, dash='dash'), showlegend=False), row=2, col=2)
if not df_survey.empty:
fig.add_trace(go.Scatter(x=df_survey['east'], y=df_survey['north'], mode='lines+markers', marker=dict(size=3, color='red'), line=dict(color='red', width=2), showlegend=False), row=1, col=2)
fig.add_trace(go.Scatter(x=df_survey['vs_calculated'], y=df_survey['tvd'], mode='lines+markers', marker=dict(size=3, color='red'), line=dict(color='red', width=2), showlegend=False), row=2, col=2)
fig.update_xaxes(title_text="Easting (m)", row=1, col=2)
fig.update_yaxes(title_text="Northing (m)", scaleanchor="x", scaleratio=1, row=1, col=2)
fig.update_xaxes(title_text="Vertical Section (m)", row=2, col=2)
fig.update_yaxes(title_text="TVD (m)", autorange='reversed', row=2, col=2)
fig.update_layout(height=650, margin=dict(l=10, r=10, t=35, b=10), scene=dict(xaxis_title="East", yaxis_title="North", zaxis_title="TVD", zaxis=dict(autorange='reversed'), aspectmode='data'))
st.plotly_chart(fig, use_container_width=True)
with col_right:
st.subheader(f"📝 Hoạt Động Giếng Khoan (Cập nhật: {selected_well['last_update']})")
tab_act, tab_fc, tab_npt = st.tabs(["📋 Hoạt động 24h qua", "🔮 Kế hoạch 24h tới", "⚠️ Báo cáo NPT"])
with tab_act:
st.info(selected_well['activity_24h_summary'])
for item in selected_well.get('operations_log', []):
st.markdown(f"- {item['time']} ({item['hours']}h): {item['desc']}")
with tab_fc:
st.success(selected_well['forecast_24h'])
with tab_npt:
if selected_well['npt_hours'] > 0:
st.error(selected_well['npt_summary'])
else:
st.success("Không ghi nhận thời gian gián đoạn NPT.")

==========================================


#6. TỔNG QUAN ĐỘI GIÀN KHOAN


==========================================

elif view_mode == "Tổng quan Đội giàn (Multi-Well 3D)":
st.subheader("🌐 Mô Hình Quỹ Đạo Đồng Thời Nhiều Giếng Khoan")
fig_multi = go.Figure()
colors = ['#2563eb', '#dc2626', '#16a34a', '#d97706']
for idx, (w_name, w_data) in enumerate(wells_db.items()):
df_w = calculate_minimum_curvature(w_data['survey_points'])
if not df_w.empty:
fig_multi.add_trace(go.Scatter3d(x=df_w['east'], y=df_w['north'], z=df_w['tvd'], mode='lines', line=dict(color=colors[idx % len(colors)], width=4), name=w_name))
fig_multi.update_layout(height=650, scene=dict(zaxis=dict(autorange='reversed'), aspectmode='data'))
st.plotly_chart(fig_multi, use_container_width=True)

==========================================


#7. NẠP BÁO CÁO DDR (TÍCH HỢP GOOGLE-GENAI AI)


==========================================

elif view_mode == "Nạp Báo Cáo DDR (PDF / AI)":
st.subheader("🤖 Bóc Tách Báo Cáo Khoan Bằng AI Gemini")
target_well = st.selectbox("Chọn giếng cần cập nhật dữ liệu:", well_names)
# Cài đặt API Key từ môi trường hệ thống hoặc nhập tay trực tiếp bảo mật
api_key_input = st.text_input("Nhập Gemini API Key của bạn (để trống nếu đã cấu hình Environment Variable):", type="password")
ddr_text_input = st.text_area("Dán nội dung văn bản báo cáo khoan DDR vào đây:", height=180)
