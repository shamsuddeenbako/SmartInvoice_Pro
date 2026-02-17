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

# 2. SESSION STATE INITIALIZATION (To remember data while editing)
if 'scanned_df' not in st.session_state:
    st.session_state.scanned_df = None
if 'grand_total' not in st.session_state:
    st.session_state.grand_total = 0

# 3. AUTOMATIC API KEY & DATABASE LOADING
try:
    # Try loading from secrets (Cloud) or environment (Local)
    if "GOOGLE_API_KEY" in st.secrets:
        os.environ["GOOGLE_API_KEY"] = st.secrets["GOOGLE_API_KEY"]
    
    # If key is set, configure it
    if os.environ.get("GOOGLE_API_KEY"):
        genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
        api_status = "✅ Connected"
    else:
        api_status = "⚠️ Missing Key"
except:
    api_status = "⚠️ Missing Key"

# Load Products (The Database)
PRODUCT_FILE = "products.csv"

def load_products():
    try:
        df = pd.read_csv(PRODUCT_FILE)
        # Ensure prices are numbers
        if df['Sale Price'].dtype == 'O':
            df['Sale Price'] = df['Sale Price'].astype(str).str.replace(',', '').astype(float)
        return df
    except:
        return pd.DataFrame(columns=["Item Description", "Sale Price"])

def save_products(df):
    df.to_csv(PRODUCT_FILE, index=False)

# Load the database into memory
df_inventory = load_products()
# Create a quick lookup dictionary: {'sugar': 1500}
product_db = {}
if not df_inventory.empty:
    # Clean string data for matching
    keys = df_inventory['Item Description'].astype(str).str.lower().str.strip()
    values = df_inventory['Sale Price']
    product_db = dict(zip(keys, values))

# 4. HELPER FUNCTIONS
def get_model():
    try:
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        flash = [m for m in models if 'flash' in m.lower()]
        return flash[0] if flash else models[0]
    except:
        return "models/gemini-1.5-flash"

def generate_receipt_image(dataframe, total):
    # Convert dataframe to list of dicts for drawing
    items = dataframe.to_dict('records')
    
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
        name = str(i['Item'])[:18]
        qty = str(i['Qty'])
        # Handle price formatting safely
        try:
            line_val = float(i['Total'])
            price = f"N{line_val:,.0f}"
        except:
            price = "N0"
            
        draw.text((30, y), qty, font=font_b, fill="black")
        draw.text((100, y), name, font=font_b, fill="black")
        draw.text((380, y), price, font=font_b, fill="black")
        y += 40
        
    draw.line([(20, y+10), (width-20, y+10)], fill="black", width=2)
    y += 30
    draw.text((30, y), "TOTAL:", font=font_bd, fill="black")
    draw.text((380, y), f"N{total:,.0f}", font=font_bd, fill="black")
    y += 60
    draw.text((width//2, y), "Thank You!", font=font_b, fill="black", anchor="mm")
    return img

# 5. MAIN NAVIGATION
st.sidebar.title("Store Controls")
st.sidebar.info(f"API: {api_status}")
st.sidebar.info(f"📦 Items Loaded: {len(product_db)}")

tab1, tab2 = st.tabs(["📝 New Sale (Scan & Edit)", "🏷️ Manage Prices"])

# --- TAB 1: SCAN AND EDIT ---
with tab1:
    st.header("New Sale")
    
    # INPUT SECTION
    col1, col2 = st.columns([2, 1])
    with col1:
        input_method = st.radio("Input:", ["📸 Camera", "📂 File Upload"], horizontal=True)
        if input_method == "📸 Camera":
            image_file = st.camera_input("Take photo")
        else:
            image_file = st.file_uploader("Upload image", type=['jpg','png','jpeg'])

    # PROCESS BUTTON
    if image_file is not None:
        if st.button("🚀 Scan Invoice"):
            if not os.environ.get("GOOGLE_API_KEY"):
                st.error("Please set API Key in secrets or sidebar.")
            else:
                with st.spinner("AI is reading & checking prices..."):
                    try:
                        img = Image.open(image_file)
                        model = genai.GenerativeModel(get_model())
                        prompt = """
                        Extract shopping list. Fix spelling. 
                        Return JSON: [{"qty":1, "item":"Milk"}]
                        """
                        response = model.generate_content([prompt, img])
                        match = re.search(r'\[.*\]', response.text, re.DOTALL)
                        
                        if match:
                            raw_data = json.loads(match.group(0))
                            
                            # Build the Data for the Editor
                            processed_data = []
                            for row in raw_data:
                                name = row.get('item', '').strip().title()
                                search_name = name.lower()
                                qty = int(row.get('qty', 1))
                                
                                # Price Lookup Logic
                                unit_price = 0
                                if search_name in product_db:
                                    unit_price = product_db[search_name]
                                else:
                                    # Fuzzy match
                                    for db_n, db_p in product_db.items():
                                        if search_name in db_n or db_n in search_name:
                                            unit_price = db_p
                                            name = db_n.title() # Auto-correct name
                                            break
                                
                                total = qty * unit_price
                                processed_data.append({
                                    "Qty": qty,
                                    "Item": name,
                                    "Unit Price": unit_price,
                                    "Total": total
                                })
                            
                            # SAVE TO SESSION STATE (So it doesn't disappear)
                            st.session_state.scanned_df = pd.DataFrame(processed_data)
                            
                        else:
                            st.error("AI couldn't see a list. Try again.")
                    except Exception as e:
                        st.error(f"Error: {e}")

    # EDITING SECTION (Only shows if we have scanned data)
    if st.session_state.scanned_df is not None:
        st.divider()
        st.subheader("✏️ Review & Edit Before Printing")
        
        # 1. THE DATA EDITOR (Excel-style editing)
        edited_df = st.data_editor(
            st.session_state.scanned_df,
            num_rows="dynamic", # Allow adding/deleting rows
            use_container_width=True,
            key="editor" # Unique key
        )
        
        # 2. RE-CALCULATE TOTAL INSTANTLY
        # We recalculate total based on user edits (Qty * Unit Price)
        edited_df["Total"] = edited_df["Qty"] * edited_df["Unit Price"]
        final_total = edited_df["Total"].sum()
        
        st.metric("Grand Total", f"₦{final_total:,.0f}")
        
        # 3. GENERATE FINAL RECEIPT
        if st.button("✅ Confirm & Print Receipt"):
            col_a, col_b = st.columns(2)
            with col_a:
                st.success("Invoice Generated!")
                # Here you would save to sales_history.csv if you want
            
            with col_b:
                receipt_img = generate_receipt_image(edited_df, final_total)
                st.image(receipt_img, caption="Final Receipt")
                
                # Download
                buf = io.BytesIO()
                receipt_img.save(buf, format="JPEG")
                st.download_button(
                    "📥 Download Image",
                    data=buf.getvalue(),
                    file_name=f"receipt_{datetime.datetime.now().strftime('%H%M%S')}.jpg",
                    mime="image/jpeg"
                )
            
            # Button to clear and start over
            if st.button("Start New Sale"):
                st.session_state.scanned_df = None
                st.rerun()

# --- TAB 2: PRICE MANAGER ---
with tab2:
    st.header("🏷️ Inventory Manager")
    st.warning("Note: If using Streamlit Cloud (Free), these changes reset when the app restarts. On Local Laptop, they are permanent.")
    
    # Load current CSV
    df_editor = load_products()
    
    # Show editable table
    updated_df = st.data_editor(
        df_editor,
        num_rows="dynamic",
        use_container_width=True
    )
    
    # Save Button
    if st.button("💾 Save Changes to Database"):
        save_products(updated_df)
        st.success("Database Updated! Restarting app to apply changes...")
        st.cache_data.clear() # Clear cache so new prices load
        st.rerun()