import streamlit as st
import google.generativeai as genai
from PIL import Image, ImageDraw, ImageFont
import io
import json
import re
import datetime
import os
import pandas as pd

# 1. SETUP PAGE
st.set_page_config(page_title="Alh Jibrin Store Pro", page_icon="🛒", layout="wide")

# 2. AUTOMATIC API KEY LOADING
# This looks for the key in your secrets file so you don't have to type it
try:
    api_key = st.secrets["GOOGLE_API_KEY"]
    os.environ["GOOGLE_API_KEY"] = api_key
    genai.configure(api_key=api_key)
    api_status = "✅ Connected"
except:
    api_key = None
    api_status = "❌ Key Missing"

# 3. LOAD SALES HISTORY
SALES_FILE = "sales_history.csv"

def load_sales():
    if os.path.exists(SALES_FILE):
        return pd.read_csv(SALES_FILE)
    return pd.DataFrame(columns=["Date", "Time", "Items", "Total"])

def save_sale(items_str, total):
    df = load_sales()
    new_data = {
        "Date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "Time": datetime.datetime.now().strftime("%H:%M:%S"),
        "Items": items_str,
        "Total": total
    }
    df = pd.concat([df, pd.DataFrame([new_data])], ignore_index=True)
    df.to_csv(SALES_FILE, index=False)

# 4. SIDEBAR
with st.sidebar:
    st.title("Store Controls")
    st.write(f"API Status: {api_status}")
    
    # Load Products
    try:
        df_prod = pd.read_csv("products.csv")
        # Clean Data
        df_prod['Item Description'] = df_prod['Item Description'].astype(str).str.lower().str.strip()
        if df_prod['Sale Price'].dtype == 'O':
             df_prod['Sale Price'] = df_prod['Sale Price'].astype(str).str.replace(',', '').astype(float)
        
        product_db = dict(zip(df_prod['Item Description'], df_prod['Sale Price']))
        st.success(f"📦 Inventory: {len(product_db)} Items")
    except:
        st.error("⚠️ products.csv not found")
        product_db = {}

# 5. RECEIPT GENERATOR FUNCTION
def generate_receipt(items, total):
    width, height = 500, 350 + (len(items) * 50)
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    
    try:
        font_h = ImageFont.truetype("arial.ttf", 40)
        font_b = ImageFont.truetype("arial.ttf", 24)
        font_bd = ImageFont.truetype("arialbd.ttf", 24)
    except:
        font_h = ImageFont.load_default()
        font_b = ImageFont.load_default()
        font_bd = ImageFont.load_default()

    draw.text((width//2, 30), "ALH JIBRIN STORE", fill="black", font=font_h, anchor="mm")
    draw.text((width//2, 80), "Provision Store, Dukku", fill="black", font=font_b, anchor="mm")
    draw.text((width//2, 120), datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), fill="black", font=font_b, anchor="mm")
    draw.line([(20, 150), (width-20, 150)], fill="black", width=2)
    
    y = 170
    draw.text((30, y), "QTY", font=font_bd, fill="black")
    draw.text((100, y), "ITEM", font=font_bd, fill="black")
    draw.text((380, y), "PRICE", font=font_bd, fill="black")
    y += 40

    for i in items:
        name = i['item'][:18]
        qty = str(i['qty'])
        price = f"N{i['line_total']:,}"
        draw.text((30, y), qty, font=font_b, fill="black")
        draw.text((100, y), name, font=font_b, fill="black")
        draw.text((380, y), price, font=font_b, fill="black")
        y += 40
        
    draw.line([(20, y+10), (width-20, y+10)], fill="black", width=2)
    y += 30
    draw.text((30, y), "TOTAL:", font=font_bd, fill="black")
    draw.text((380, y), f"N{total:,}", font=font_bd, fill="black")
    y += 60
    draw.text((width//2, y), "Thank You!", font=font_b, fill="black", anchor="mm")
    return img

# 6. MAIN TABS
tab1, tab2 = st.tabs(["📝 New Sale", "📊 Manager Dashboard"])

with tab1:
    uploaded_file = st.file_uploader("Snap a picture", type=["jpg", "jpeg", "png"])
    
    if uploaded_file and st.button("Process Invoice"):
        if not api_key:
            st.error("API Key missing. Check secrets.toml")
        else:
            with st.spinner('Processing...'):
                try:
                    img = Image.open(uploaded_file)
                    model = genai.GenerativeModel("gemini-1.5-flash")
                    prompt = """
                    Extract shopping list from image. 
                    Fix spelling (e.g. 'Semov' -> 'Semovita'). 
                    Return JSON: [{"qty":1, "item":"Milk"}]
                    """
                    response = model.generate_content([prompt, img])
                    raw = json.loads(re.search(r'\[.*\]', response.text, re.DOTALL).group(0))
                    
                    final_total = 0
                    clean_items = []
                    names = []
                    
                    for row in raw:
                        name = row.get('item', '').lower().strip()
                        qty = row.get('qty', 1)
                        price = 0
                        
                        # Price Match
                        if name in product_db:
                            price = product_db[name]
                        else:
                            for db_n, db_p in product_db.items():
                                if name in db_n or db_n in name:
                                    price = db_p
                                    row['item'] = db_n.title()
                                    break
                        
                        total = qty * price
                        final_total += total
                        clean_items.append({"qty":qty, "item":row['item'].title(), "line_total":total})
                        names.append(row['item'])
                        
                    # Save & Show
                    save_sale(", ".join(names), final_total)
                    
                    c1, c2 = st.columns(2)
                    with c1:
                        st.table(clean_items)
                        st.metric("Total", f"N{final_total:,}")
                    with c2:
                        rec_img = generate_receipt(clean_items, final_total)
                        st.image(rec_img, width=300)
                        
                        buf = io.BytesIO()
                        rec_img.save(buf, format="JPEG")
                        st.download_button("Download Receipt", buf.getvalue(), "receipt.jpg", "image/jpeg")
                        
                except Exception as e:
                    st.error(f"Error: {e}")

with tab2:
    st.header("Sales History")
    df = load_sales()
    if not df.empty:
        st.metric("Total Revenue", f"N{df['Total'].sum():,}")
        st.dataframe(df, use_container_width=True)
        st.download_button("Download Excel Report", df.to_csv(index=False), "report.csv")
    else:
        st.info("No sales yet.")