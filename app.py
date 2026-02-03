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
try:
    api_key = st.secrets["GOOGLE_API_KEY"]
    os.environ["GOOGLE_API_KEY"] = api_key
    genai.configure(api_key=api_key)
    api_status = "✅ Connected"
except:
    # Fallback if secrets are not set (e.g. running locally without secrets.toml)
    api_key = None
    api_status = "⚠️ Key Missing"

# 3. SALES HISTORY LOGIC
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

# 4. HELPER: FIND THE CORRECT MODEL NAME
def get_model():
    """Dynamically finds the best available Gemini Flash model"""
    try:
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        # Look for any model with 'flash' in the name
        flash_models = [m for m in models if 'flash' in m.lower()]
        if flash_models:
            return flash_models[0] # Return the first one found (e.g. models/gemini-1.5-flash-latest)
        return models[0] # Fallback to whatever is available
    except Exception as e:
        st.error(f"Error finding models: {e}")
        return "gemini-pro" # Emergency fallback

# 5. SIDEBAR
with st.sidebar:
    st.title("Store Controls")
    st.write(f"API Status: {api_status}")
    
    # If key is missing from secrets, allow manual entry
    if not api_key:
        api_key = st.text_input("Enter Google API Key", type="password")
        if api_key:
            os.environ["GOOGLE_API_KEY"] = api_key
            genai.configure(api_key=api_key)
    
    # Load Products
    try:
        df_prod = pd.read_csv("products.csv")
        df_prod['Item Description'] = df_prod['Item Description'].astype(str).str.lower().str.strip()
        if df_prod['Sale Price'].dtype == 'O':
             df_prod['Sale Price'] = df_prod['Sale Price'].astype(str).str.replace(',', '').astype(float)
        
        product_db = dict(zip(df_prod['Item Description'], df_prod['Sale Price']))
        st.success(f"📦 Inventory: {len(product_db)} Items")
    except:
        st.warning("⚠️ products.csv not found. Using AI prices.")
        product_db = {}

# 6. RECEIPT GENERATOR
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

# 7. MAIN TABS
tab1, tab2 = st.tabs(["📝 New Sale", "📊 Manager Dashboard"])

with tab1:
    uploaded_file = st.file_uploader("Snap a picture", type=["jpg", "jpeg", "png"])
    
    if uploaded_file and st.button("Process Invoice"):
        if not api_key:
            st.error("Please enter API Key in sidebar or secrets.toml")
        else:
            with st.spinner('Processing...'):
                try:
                    img = Image.open(uploaded_file)
                    
                    # --- THIS IS THE FIX ---
                    model_name = get_model() # We ask the system for the name
                    model = genai.GenerativeModel(model_name)
                    # -----------------------
                    
                    prompt = """
                    Extract shopping list from image. 
                    Fix spelling (e.g. 'Semov' -> 'Semovita'). 
                    Return JSON: [{"qty":1, "item":"Milk"}]
                    """
                    response = model.generate_content([prompt, img])
                    
                    match = re.search(r'\[.*\]', response.text, re.DOTALL)
                    if not match:
                        st.error("Could not find list in image. Try again.")
                        st.stop()
                        
                    raw = json.loads(match.group(0))
                    
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
                    if "429" in str(e):
                        st.warning("🚦 Speed Limit Hit. Wait 30 seconds.")
                    else:
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