# ==============================================================================
# ADIKA MARKETPLACE BOT - CLEAN VERSION
# ==============================================================================

import logging
import os
import re
import asyncio
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any

import psycopg2
from psycopg2.extras import RealDictCursor
import sqlite3

from flask import Flask, request, jsonify, render_template_string

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

# ==============================================================================
# 1. CONFIGURATION & LOGGING
# ==============================================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "0")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not BOT_TOKEN:
    raise RuntimeError("âŒ BOT_TOKEN environment variable á‹áˆµáŒ¥ áŠ áˆá‰°áŒˆáŠ˜áˆá¢")

ADMIN_CHAT_ID_INT = int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID else 0
DB_FILE = "adika_marketplace.db"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Global bot application (for Flask notifications)
bot_app: Optional[Application] = None

# ==============================================================================
# 2. FLASK WEB SERVER & WEBAPP
# ==============================================================================

web_app = Flask(__name__)

SELLER_FORM_HTML = """
<!DOCTYPE html>
<html>
<head>
   <meta charset="UTF-8">
   <meta name="viewport" content="width=device-width, initial-scale=1.0">
   <script src="https://telegram.org/js/telegram-web-app.js"></script>
   <script src="https://cdn.tailwindcss.com"></script>
   <style>
       .image-preview-container { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
       .image-preview-wrapper { position: relative; }
       .image-preview { width: 80px; height: 80px; object-fit: cover; border-radius: 8px; border: 2px solid #e5e7eb; }
       .remove-btn { position: absolute; top: -6px; right: -6px; background: #ef4444; color: white; border-radius: 50%; width: 22px; height: 22px; font-size: 14px; display: flex; align-items: center; justify-content: center; cursor: pointer; border: none; }
       .urgent-badge { background-color: #ef4444; color: white; padding: 2px 8px; border-radius: 9999px; font-size: 12px; font-weight: bold; animation: pulse 1.5s infinite; }
       @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.6; } }
   </style>
</head>
<body class="bg-gray-100 p-4">
   <div class="max-w-md mx-auto bg-white p-6 rounded-xl shadow-md">
       <h2 class="text-xl font-bold mb-4 text-center">áŠ•á‰¥áˆ¨á‰µ áˆˆáŒˆá‰ á‹« á‹«á‰…áˆ­á‰¡</h2>
       <form id="listingForm" class="space-y-4">
           <!-- á‹‹áŠ“ áˆá‹µá‰¥ -->
           <div>
               <label class="block text-sm font-medium text-gray-700 mb-1">ðŸ“¦ á‹‹áŠ“ áˆá‹µá‰¥</label>
               <select id="category" class="w-full p-2 border rounded focus:ring-2 focus:ring-blue-500">
                   <option value="áˆ˜áŠªáŠ“">ðŸš— áˆ˜áŠªáŠ“</option>
                   <option value="á‰¤á‰µ">ðŸ  á‰¤á‰µ</option>
               </select>
           </div>
          
           <!-- á‰°áˆˆá‹‹á‹‹áŒ­ áˆ›áŒ£áˆªá‹«á‹Žá‰½ -->
           <div id="dynamicFilters"></div>
          
           <!-- á‹‹áŒ‹ -->
           <div>
               <label class="block text-sm font-medium text-gray-700 mb-1">ðŸ’° á‹‹áŒ‹ (á‰ á‰¥áˆ­)</label>
               <input type="number" id="price" placeholder="áˆˆáˆáˆ³áˆŒá¦ 2500000" class="w-full p-2 border rounded" required>
           </div>
           <div class="flex items-center gap-2">
               <input type="checkbox" id="negotiable" checked class="w-4 h-4 text-blue-600">
               <label for="negotiable" class="text-sm text-gray-700">ðŸ’° á‹‹áŒ‹á‹ á‹¨áˆšá‹°áˆ«á‹°áˆ­ áŠá‹</label>
           </div>
          
           <!-- áŠ áˆµá‰¸áŠ³á‹­ áˆ½á‹«áŒ­ -->
           <div class="flex items-center gap-2 bg-red-50 p-3 rounded-lg border border-red-200">
               <input type="checkbox" id="urgentSale" class="w-4 h-4 text-red-600">
               <label for="urgentSale" class="text-sm font-medium text-red-700">âš¡ áŠ áˆµá‰¸áŠ³á‹­ áˆ½á‹«áŒ­ (Urgent Sale)</label>
           </div>
          
           <!-- áˆ˜áŒáˆˆáŒ« -->
           <div>
               <label class="block text-sm font-medium text-gray-700 mb-1">ðŸ“ á‹áˆ­á‹áˆ­ áˆ˜áŒáˆˆáŒ«</label>
               <textarea id="description" placeholder="á‹¨áŠ•á‰¥áˆ¨á‰±áŠ• áˆ™áˆ‰ á‹áˆ­á‹áˆ­ áˆ˜áˆ¨áŒƒ á‹«áˆµáŒˆá‰¡..." class="w-full p-2 border rounded h-24" required></textarea>
           </div>
          
           <!-- áŽá‰¶ áˆ˜áŒ«áŠ› (á‰¥á‹™ áŽá‰¶ á‹­á‹°áŒá‹áˆ) -->
           <div>
               <label class="block text-sm font-medium text-gray-700 mb-1">ðŸ“¸ áŽá‰¶á‹Žá‰½ (áŠ¥áˆµáŠ¨ 5)</label>
               <input type="file" id="photos" accept="image/*" multiple class="w-full p-2 border rounded text-sm">
               <p class="text-xs text-gray-500 mt-1">áŽá‰¶á‹Žá‰½ á‰ áˆ«áˆµ-áˆ°áˆ­ á‹­áŒ¨áˆ˜á‰ƒáˆ‰ â€¢ áŠ¨1 á‰ áˆ‹á‹­ áˆ˜áˆáˆ¨áŒ¥ á‹­á‰½áˆ‹áˆ‰</p>
               <div id="photoPreviews" class="image-preview-container"></div>
           </div>
          
           <!-- á‹¨áˆ˜áŒˆáŠ“áŠ› áˆ˜áˆ¨áŒƒ -->
           <div>
               <label class="block text-sm font-medium text-gray-700 mb-1">ðŸ“ž áˆµáˆáŠ­ á‰áŒ¥áˆ­</label>
               <input type="tel" id="phone" placeholder="0911223344" class="w-full p-2 border rounded" required>
           </div>
           <div>
               <label class="block text-sm font-medium text-gray-700 mb-1">ðŸ“± Telegram Username (áŠ áˆ›áˆ«áŒ­)</label>
               <input type="text" id="telegramUser" placeholder="@username" class="w-full p-2 border rounded">
           </div>
          
           <!-- á‰áˆáŽá‰½ -->
           <div class="flex gap-3 pt-4">
               <button type="submit" id="submitBtn" class="flex-1 bg-blue-600 text-white p-3 rounded font-bold hover:bg-blue-700 transition">âœ… áŠ áˆ¨áŒ‹áŒáŒ¥áŠ“ áˆˆáŒ¥á</button>
               <button type="button" id="cancelBtn" class="flex-1 bg-gray-400 text-white p-3 rounded font-bold hover:bg-gray-500 transition">âŒ áˆ°áˆ­á‹</button>
           </div>
       </form>
       <p id="statusMsg" class="text-center mt-4 text-sm hidden"></p>
   </div>

   <script>
       let tg = window.Telegram.WebApp;
       tg.expand();
       tg.ready();

       // ========== DYNAMIC FILTERS ==========
       const categorySelect = document.getElementById('category');
       const dynamicFiltersDiv = document.getElementById('dynamicFilters');

       const carFiltersHTML = `
           <div class="space-y-3 border-t pt-3">
               <div>
                   <label class="block text-sm font-medium text-gray-700 mb-1">â›½ á‹¨áŠá‹³áŒ… áŠ á‹­áŠá‰µ</label>
                   <select id="fuelType" class="w-full p-2 border rounded">
                       <option value="">-- á‹­áˆáˆ¨áŒ¡ --</option>
                       <option value="á‰¤áŠ•á‹šáŠ•">â›½ á‰¤áŠ•á‹šáŠ•</option>
                       <option value="áŠ“ááŒ£">ðŸ›¢ï¸ áŠ“ááŒ£</option>
                       <option value="áŠ¤áˆŒáŠ­á‰µáˆªáŠ­">âš¡ áŠ¤áˆŒáŠ­á‰µáˆªáŠ­</option>
                       <option value="áˆ€á‹­á‰¥áˆªá‹µ">ðŸ”‹ áˆ€á‹­á‰¥áˆªá‹µ</option>
                   </select>
               </div>
               <div>
                   <label class="block text-sm font-medium text-gray-700 mb-1">âš™ï¸ áˆ›áˆ­áˆ½ (Transmission)</label>
                   <select id="transmission" class="w-full p-2 border rounded">
                       <option value="">-- á‹­áˆáˆ¨áŒ¡ --</option>
                       <option value="áˆ›áŠ•á‹‹áˆ">ðŸ•¹ï¸ áˆ›áŠ•á‹‹áˆ</option>
                       <option value="áŠ¦á‰¶áˆ›á‰²áŠ­">ðŸ¤– áŠ¦á‰¶áˆ›á‰²áŠ­</option>
                   </select>
               </div>
               <div>
                   <label class="block text-sm font-medium text-gray-700 mb-1">ðŸ›£ï¸ á‹¨áŠªáˆŽáˆœá‰µáˆ­ áˆ˜áŒ áŠ• (KM)</label>
                   <input type="number" id="mileage" placeholder="áˆˆáˆáˆ³áˆŒá¦ 50000" class="w-full p-2 border rounded">
               </div>
               <div>
                   <label class="block text-sm font-medium text-gray-700 mb-1">ðŸ“Š áˆáŠ”á‰³</label>
                   <select id="condition" class="w-full p-2 border rounded">
                       <option value="">-- á‹­áˆáˆ¨áŒ¡ --</option>
                       <option value="áŠ á‹²áˆµ">ðŸ†• áŠ á‹²áˆµ</option>
                       <option value="á‹«áŒˆáˆˆáŒˆáˆˆ">âœ… á‹«áŒˆáˆˆáŒˆáˆˆ</option>
                       <option value="áŒ¥áŒˆáŠ“ á‹¨áˆšáˆáˆáŒ">ðŸ”§ áŒ¥áŒˆáŠ“ á‹¨áˆšáˆáˆáŒ</option>
                   </select>
               </div>
               <div>
                   <label class="block text-sm font-medium text-gray-700 mb-1">ðŸš— á‹¨áˆ˜áŠªáŠ“ áŠ á‹­áŠá‰µ/áˆžá‹´áˆ</label>
                   <select id="carType" class="w-full p-2 border rounded">
                       <option value="">-- á‹­áˆáˆ¨áŒ¡ --</option>
                       <option value="á‹¨á‰¤á‰µ áˆ˜áŠªáŠ“">ðŸš— á‹¨á‰¤á‰µ áˆ˜áŠªáŠ“</option>
                       <option value="á‹¨áˆ¥áˆ« áˆ˜áŠªáŠ“">ðŸšš á‹¨áˆ¥áˆ« áˆ˜áŠªáŠ“</option>
                       <option value="áŠ¨á‰£á‹µ á‰°áˆ½áŠ¨áˆ­áŠ«áˆª">ðŸšœ áŠ¨á‰£á‹µ á‰°áˆ½áŠ¨áˆ­áŠ«áˆª</option>
                   </select>
               </div>
           </div>
       `;

       const houseFiltersHTML = `
           <div class="space-y-3 border-t pt-3">
               <div>
                   <label class="block text-sm font-medium text-gray-700 mb-1">ðŸ›ï¸ á‹¨áˆ˜áŠá‰³ áŠ­ááˆ á‰¥á‹›á‰µ</label>
                   <select id="bedrooms" class="w-full p-2 border rounded">
                       <option value="">-- á‹­áˆáˆ¨áŒ¡ --</option>
                       <option value="1">1</option><option value="2">2</option><option value="3">3</option>
                       <option value="4">4</option><option value="5+">5+</option>
                   </select>
               </div>
               <div>
                   <label class="block text-sm font-medium text-gray-700 mb-1">ðŸ› á‹¨áˆ˜á‰³áŒ á‰¢á‹« áŠ­ááˆ á‰¥á‹›á‰µ</label>
                   <select id="bathrooms" class="w-full p-2 border rounded">
                       <option value="">-- á‹­áˆáˆ¨áŒ¡ --</option>
                       <option value="1">1</option><option value="2">2</option><option value="3">3</option>
                       <option value="4+">4+</option>
                   </select>
               </div>
               <div class="flex items-center gap-2">
                   <input type="checkbox" id="parking" class="w-4 h-4 text-blue-600">
                   <label for="parking" class="text-sm text-gray-700">ðŸš— á“áˆ­áŠªáŠ•áŒ áŠ áˆˆá‹</label>
               </div>
               <div>
                   <label class="block text-sm font-medium text-gray-700 mb-1">ðŸ“Š áˆáŠ”á‰³</label>
                   <select id="houseCondition" class="w-full p-2 border rounded">
                       <option value="">-- á‹­áˆáˆ¨áŒ¡ --</option>
                       <option value="áŠ á‹²áˆµ">ðŸ†• áŠ á‹²áˆµ</option>
                       <option value="áŒ¥áˆ©">âœ… áŒ¥áˆ©</option>
                       <option value="áŠ¥á‹µáˆ³á‰µ á‹¨áˆšáˆáˆáŒ">ðŸ”§ áŠ¥á‹µáˆ³á‰µ á‹¨áˆšáˆáˆáŒ</option>
                   </select>
               </div>
               <div>
                   <label class="block text-sm font-medium text-gray-700 mb-1">ðŸ  á‹¨á‰¤á‰µ áŠ á‹­áŠá‰µ</label>
                   <select id="houseType" class="w-full p-2 border rounded">
                       <option value="">-- á‹­áˆáˆ¨áŒ¡ --</option>
                       <option value="á‰ªáˆ‹">ðŸ¡ á‰ªáˆ‹</option>
                       <option value="áŠ á“áˆ­á‰³áˆ›">ðŸ¢ áŠ á“áˆ­á‰³áˆ›</option>
                       <option value="áŠ®áŠ•á‹¶áˆšáŠ’á‹¨áˆ">ðŸ¢ áŠ®áŠ•á‹¶áˆšáŠ’á‹¨áˆ</option>
                       <option value="áˆªáˆ áŠ¥áˆµá‰´á‰µ">ðŸ¢ áˆªáˆ áŠ¥áˆµá‰´á‰µ</option>
                       <option value="áˆ˜áˆ¬á‰µ">ðŸžï¸ áˆ˜áˆ¬á‰µ/á‰¦á‰³</option>
                   </select>
               </div>
           </div>
       `;

       function updateFilters() {
           dynamicFiltersDiv.innerHTML = categorySelect.value === 'áˆ˜áŠªáŠ“' ? carFiltersHTML : houseFiltersHTML;
       }
       categorySelect.addEventListener('change', updateFilters);
       updateFilters();

       // ========== MULTI-PHOTO WITH ACCUMULATION ==========
       const photoInput = document.getElementById('photos');
       const previewDiv = document.getElementById('photoPreviews');
       let compressedFiles = [];   // áŠ¥á‹šáˆ… áŠá‹ á‹¨áˆšáŠ¨áˆ›á‰¹á‰µ

       async function compressImage(file) {
           return new Promise((resolve) => {
               const reader = new FileReader();
               reader.onload = (e) => {
                   const img = new Image();
                   img.onload = () => {
                       const canvas = document.createElement('canvas');
                       let width = img.width;
                       let height = img.height;
                       const maxDim = 1200;
                       if (width > maxDim || height > maxDim) {
                           if (width > height) { height = (height / width) * maxDim; width = maxDim; }
                           else { width = (width / height) * maxDim; height = maxDim; }
                       }
                       canvas.width = width;
                       canvas.height = height;
                       const ctx = canvas.getContext('2d');
                       ctx.drawImage(img, 0, 0, width, height);
                       canvas.toBlob((blob) => {
                           resolve(new File([blob], file.name, { type: 'image/jpeg', lastModified: Date.now() }));
                       }, 'image/jpeg', 0.7);
                   };
                   img.src = e.target.result;
               };
               reader.readAsDataURL(file);
           });
       }

       function renderPreviews() {
           previewDiv.innerHTML = '';
           compressedFiles.forEach((file, index) => {
               const reader = new FileReader();
               reader.onload = (e) => {
                   const wrapper = document.createElement('div');
                   wrapper.className = 'image-preview-wrapper';

                   const img = document.createElement('img');
                   img.src = e.target.result;
                   img.className = 'image-preview';

                   const removeBtn = document.createElement('button');
                   removeBtn.className = 'remove-btn';
                   removeBtn.innerHTML = 'Ã—';
                   removeBtn.type = 'button';
                   removeBtn.onclick = () => {
                       compressedFiles.splice(index, 1);
                       renderPreviews();
                   };

                   wrapper.appendChild(img);
                   wrapper.appendChild(removeBtn);
                   previewDiv.appendChild(wrapper);
               };
               reader.readAsDataURL(file);
           });
       }

       photoInput.addEventListener('change', async () => {
           const newFiles = Array.from(photoInput.files);
           if (newFiles.length === 0) return;

           // áŠ á‹²áˆµ áŽá‰¶á‹Žá‰½áŠ• áŒ¨áˆáˆ­ (áŠ á‰µáŒ¥á‹)
           for (const file of newFiles) {
               if (compressedFiles.length >= 5) break;
               const compressed = await compressImage(file);
               compressedFiles.push(compressed);
           }

           // input áŠ• áŠ áŒ½á‹³ (á‰°áˆ˜áˆ³áˆ³á‹­ áŽá‰¶ áŠ¥áŠ•á‹°áŒˆáŠ“ áˆˆáˆ˜áˆáˆ¨áŒ¥)
           photoInput.value = '';
           renderPreviews();
       });

       // ========== FORM SUBMISSION ==========
       document.getElementById('cancelBtn').addEventListener('click', () => {
           if (confirm('áŠ¥áˆ­áŒáŒ áŠ› áŠá‹Žá‰µ? áˆáˆ‰áˆ á‹«áˆµáŒˆá‰¡á‰µ áˆ˜áˆ¨áŒƒ á‹­áŒ á‹áˆá¢')) {
               tg.close();
           }
       });

       document.getElementById('listingForm').onsubmit = async (e) => {
           e.preventDefault();
           const btn = document.getElementById('submitBtn');
           const status = document.getElementById('statusMsg');
           btn.disabled = true;
           btn.innerText = "áŠ¥á‹¨á‰°áˆ‹áŠ¨ áŠá‹...";
           status.classList.add('hidden');

           const isCar = categorySelect.value === 'áˆ˜áŠªáŠ“';

           const extraData = isCar ? {
               fuel_type: document.getElementById('fuelType')?.value || '',
               transmission: document.getElementById('transmission')?.value || '',
               mileage: document.getElementById('mileage')?.value || '',
               condition: document.getElementById('condition')?.value || '',
               car_type: document.getElementById('carType')?.value || '',
           } : {
               bedrooms: document.getElementById('bedrooms')?.value || '',
               bathrooms: document.getElementById('bathrooms')?.value || '',
               parking: document.getElementById('parking')?.checked ? 'áŠ áˆˆ' : 'á‹¨áˆˆáˆ',
               condition: document.getElementById('houseCondition')?.value || '',
               house_type: document.getElementById('houseType')?.value || '',
           };

           const data = {
               user_id: tg.initDataUnsafe.user ? tg.initDataUnsafe.user.id : "unknown",
               category: categorySelect.value,
               price: document.getElementById('price').value,
               negotiable: document.getElementById('negotiable').checked,
               urgent_sale: document.getElementById('urgentSale').checked,
               description: document.getElementById('description').value,
               phone: document.getElementById('phone').value,
               telegram_user: document.getElementById('telegramUser').value || '',
               ...extraData
           };

           try {
               if (compressedFiles.length > 0) {
                   const photoPromises = compressedFiles.map(f => {
                       return new Promise((resolve) => {
                           const reader = new FileReader();
                           reader.onload = (ev) => resolve(ev.target.result);
                           reader.readAsDataURL(f);
                       });
                   });
                   data.photos = await Promise.all(photoPromises);
               }

               const res = await fetch('/api/submit-listing', {
                   method: 'POST',
                   headers: {'Content-Type': 'application/json'},
                   body: JSON.stringify(data)
               });
               const result = await res.json();

               if (result.status === "success") {
                   // âœ… á‹¨á‰°áˆ»áˆ»áˆˆ áˆ›áˆ³á‹ˆá‰‚á‹«
                   status.innerHTML = `
                       <div class="text-green-600 font-medium">
                           âœ… áˆ›áˆµá‰³á‹ˆá‰‚á‹«á‹Ž á‰ áˆµáŠ¬á‰µ á‰°áˆ˜á‹áŒá‰§áˆ!<br>
                           ðŸ†” á‰áŒ¥áˆ­á¦ <b>#ADK-${result.req_id}</b><br><br>
                           ðŸ“¬ áˆˆáˆáˆ‰áˆ á‹°áˆ‹áˆŽá‰½ á‰°áˆáŠ³áˆá¢<br>
                           ðŸ—‘ï¸ áˆ›áˆµá‰³á‹ˆá‰‚á‹«á‹áŠ• áˆ›áŒ¥á‹á‰µ áŠ¨áˆáˆˆáŒ‰<br>
                           áŠ¨áŒˆá‰ á‹« á‰¦á‰³ áŒˆá‰¥á‰°á‹ <b>áŠ áŒ¥á‹</b> á‰áˆááŠ• á‹­áŒ«áŠ‘á¢
                       </div>
                   `;
                   status.classList.remove('hidden');
                   document.getElementById('listingForm').classList.add('hidden');
                   setTimeout(() => tg.close(), 4000);
               } else {
                   status.innerText = "âŒ " + (result.message || "áˆµáˆ…á‰°á‰µ á‰°áŠ¨áˆµá‰·áˆ");
                   status.classList.remove('hidden');
                   status.classList.add('text-red-600');
                   btn.disabled = false;
                   btn.innerText = "âœ… áŠ áˆ¨áŒ‹áŒáŒ¥áŠ“ áˆˆáŒ¥á";
               }
           } catch (err) {
               status.innerText = "âŒ á‹¨áŠ”á‰µá‹ˆáˆ­áŠ­ áˆµáˆ…á‰°á‰µá¢ áŠ¥áŠ•á‹°áŒˆáŠ“ á‹­áˆžáŠ­áˆ©á¢";
               status.classList.remove('hidden');
               status.classList.add('text-red-600');
               btn.disabled = false;
               btn.innerText = "âœ… áŠ áˆ¨áŒ‹áŒáŒ¥áŠ“ áˆˆáŒ¥á";
           }
       };
   </script>
</body>
</html>
"""

BUYER_FORM_HTML = """
<!DOCTYPE html>
<html>
<head>
   <meta charset="UTF-8">
   <meta name="viewport" content="width=device-width, initial-scale=1.0">
   <script src="https://telegram.org/js/telegram-web-app.js"></script>
   <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 p-4">
   <div class="max-w-md mx-auto bg-white p-6 rounded-xl shadow-md">
       <h2 class="text-xl font-bold mb-4 text-center">á‹¨áˆšáˆáˆáŒ‰á‰µáŠ• áŠ•á‰¥áˆ¨á‰µ á‹­áŒáˆˆáŒ¹</h2>
       <form id="buyerForm" class="space-y-4">
           <div>
               <label class="block text-sm font-medium text-gray-700 mb-1">ðŸ“¦ áˆá‹µá‰¥</label>
               <select id="category" class="w-full p-2 border rounded">
                   <option value="áˆ˜áŠªáŠ“">ðŸš— áˆ˜áŠªáŠ“</option>
                   <option value="á‰¤á‰µ">ðŸ  á‰¤á‰µ</option>
               </select>
           </div>
          
           <div>
               <label class="block text-sm font-medium text-gray-700 mb-1">ðŸ’° á‹¨á‰ áŒ€á‰µ áŠ­áˆáˆ (á‰ á‰¥áˆ­)</label>
               <div class="flex gap-2">
                   <input type="number" id="budgetMin" placeholder="áŠ¨" class="w-1/2 p-2 border rounded">
                   <input type="number" id="budgetMax" placeholder="áŠ¥áˆµáŠ¨" class="w-1/2 p-2 border rounded">
               </div>
           </div>
          
           <div class="flex items-center gap-2 bg-blue-50 p-3 rounded-lg border border-blue-200">
               <input type="checkbox" id="createAlert" class="w-4 h-4 text-blue-600">
               <label for="createAlert" class="text-sm font-medium text-blue-700">ðŸ”” á‰°áˆ˜áˆ³áˆ³á‹­ áŠ•á‰¥áˆ¨á‰µ áˆ²áˆˆá‰€á‰… á‹­á‹µáˆ¨áˆ°áŠ</label>
           </div>
          
           <textarea id="details" placeholder="á‹áˆ­á‹áˆ­ ááˆ‹áŒŽá‰µá‹ŽáŠ• á‹«áˆµáŒˆá‰¡..." class="w-full p-2 border rounded h-24" required></textarea>
           <input type="tel" id="phone" placeholder="áˆµáˆáŠ­ á‰áŒ¥áˆ­" class="w-full p-2 border rounded" required>
           <input type="text" id="telegramUser" placeholder="Telegram Username (áŠ áˆ›áˆ«áŒ­)" class="w-full p-2 border rounded">
          
           <div class="flex gap-3 pt-4">
               <button type="submit" id="submitBtn" class="flex-1 bg-green-600 text-white p-3 rounded font-bold hover:bg-green-700 transition">âœ… áŒ¥á‹«á‰„á‹áŠ• á‹­áˆ‹áŠ©</button>
               <button type="button" id="cancelBtn" class="flex-1 bg-gray-400 text-white p-3 rounded font-bold hover:bg-gray-500 transition">âŒ áˆ°áˆ­á‹</button>
           </div>
       </form>
       <p id="statusMsg" class="text-center mt-4 text-sm hidden"></p>
   </div>
   <script>
       let tg = window.Telegram.WebApp;
       tg.expand();
       tg.ready();
      
       document.getElementById('cancelBtn').addEventListener('click', () => tg.close());
      
       document.getElementById('buyerForm').onsubmit = async (e) => {
           e.preventDefault();
           const btn = document.getElementById('submitBtn');
           const status = document.getElementById('statusMsg');
           btn.disabled = true;
           btn.innerText = "áŠ¥á‹¨á‰°áˆ‹áŠ¨ áŠá‹...";
           status.classList.add('hidden');
          
           const data = {
               user_id: tg.initDataUnsafe.user ? tg.initDataUnsafe.user.id : "unknown",
               category: document.getElementById('category').value,
               budget_min: document.getElementById('budgetMin').value,
               budget_max: document.getElementById('budgetMax').value,
               create_alert: document.getElementById('createAlert').checked,
               details: document.getElementById('details').value,
               phone: document.getElementById('phone').value,
               telegram_user: document.getElementById('telegramUser').value || ''
           };
          
           try {
               const res = await fetch('/api/submit-request', {
                   method: 'POST',
                   headers: {'Content-Type': 'application/json'},
                   body: JSON.stringify(data)
               });
               const result = await res.json();
              
               if (result.status === "success") {
                   status.innerHTML = `<span class="text-green-600">âœ… áŒ¥á‹«á‰„á‹Ž á‰°áˆ˜á‹áŒá‰§áˆ!</span><br>ðŸ†” á‰áŒ¥áˆ­á¦ <b>#ADK-${result.req_id}</b>`;
                   status.classList.remove('hidden');
                   setTimeout(() => tg.close(), 2000);
               } else {
                   status.innerText = "âŒ " + (result.message || "áˆµáˆ…á‰°á‰µ á‰°áŠ¨áˆµá‰·áˆ");
                   status.classList.remove('hidden');
                   status.classList.add('text-red-600');
                   btn.disabled = false;
                   btn.innerText = "âœ… áŒ¥á‹«á‰„á‹áŠ• á‹­áˆ‹áŠ©";
               }
           } catch (err) {
               status.innerText = "âŒ á‹¨áŠ”á‰µá‹ˆáˆ­áŠ­ áˆµáˆ…á‰°á‰µá¢";
               status.classList.remove('hidden');
               status.classList.add('text-red-600');
               btn.disabled = false;
               btn.innerText = "âœ… áŒ¥á‹«á‰„á‹áŠ• á‹­áˆ‹áŠ©";
           }
       };
   </script>
</body>
</html>
"""

@web_app.route('/')
def home():
   return "âœ… Adika Marketplace Bot á‰ áˆµáŠ¬á‰µ áŠ¥á‹¨áˆ°áˆ« á‹­áŒˆáŠ›áˆ!", 200

@web_app.route('/seller-form')
def webapp_seller_form():
   return render_template_string(SELLER_FORM_HTML)

@web_app.route('/buyer-form')
def webapp_buyer_form():
   return render_template_string(BUYER_FORM_HTML)

def _send_notification_safe(notification_text: str, req_id: int, buyer_id: int):
   """áŠ¨ Flask á‹áˆµáŒ¥ á‰ áŠ áˆµá‰°áˆ›áˆ›áŠ áˆ˜áŠ•áŒˆá‹µ áˆˆá‹°áˆ‹áˆŽá‰½ áˆ›áˆ³á‹ˆá‰‚á‹« áˆ˜áˆ‹áŠ­"""
   if not bot_app:
       logger.warning("bot_app is None â€“ cannot send notification")
       return
   try:
       async def _notify():
           await notify_brokers(bot_app.bot, notification_text, req_id, buyer_id)
       def run_in_thread():
           try:
               loop = asyncio.new_event_loop()
               asyncio.set_event_loop(loop)
               loop.run_until_complete(_notify())
               loop.close()
               logger.info(f"âœ… Notification sent for req_id={req_id}")
           except Exception as e:
               logger.error(f"âŒ Notification thread error: {e}", exc_info=True)
       t = threading.Thread(target=run_in_thread, daemon=True)
       t.start()
   except Exception as e:
       logger.error(f"âŒ Failed to start notification thread: {e}", exc_info=True)

@web_app.route('/api/submit-listing', methods=['POST'])
def submit_listing():
   try:
       data = request.json or {}
       user_id = data.get('user_id')
       category = data.get('category', 'áˆ˜áŠªáŠ“')
       price = data.get('price', '')
       negotiable = data.get('negotiable', True)
       urgent_sale = data.get('urgent_sale', False)
       description = data.get('description', '')
       phone = data.get('phone', '')
       telegram_user = data.get('telegram_user', '')
      
       fuel_type = data.get('fuel_type', '')
       transmission = data.get('transmission', '')
       mileage = data.get('mileage', '')
       condition = data.get('condition', '')
       car_type = data.get('car_type', '')
      
       bedrooms = data.get('bedrooms', '')
       bathrooms = data.get('bathrooms', '')
       parking = data.get('parking', '')
       house_condition = data.get('condition', '')
       house_type = data.get('house_type', '')
      
       photos = data.get('photos', [])
       logger.info(f"ðŸ“¥ Seller WebApp data: {data}")

       if not user_id or user_id == "unknown":
           return jsonify({"status": "error", "message": "User ID áŠ áˆá‰°áŒˆáŠ˜áˆá¢ Telegram á‹áˆµáŒ¥ áŠ­áˆá‰µá¢"}), 400

       negotiable_text = "âœ… á‹¨áˆšá‹°áˆ«á‹°áˆ­" if negotiable else "âŒ á‹¨áˆ›á‹­á‹°áˆ«á‹°áˆ­"
       urgent_text = "âš¡ **áŠ áˆµá‰¸áŠ³á‹­ áˆ½á‹«áŒ­!** " if urgent_sale else ""
      
       # áŠ•áŒ¹áˆ… áˆ˜áŒáˆˆáŒ« (áŠ áˆ‹áˆµáˆáˆ‹áŒŠ áŒ½áˆáŽá‰½ á‰°á‹ˆáŒá‹°á‹‹áˆ)
       full_desc = f"{urgent_text}"
       full_desc += f"ðŸ’° á‹‹áŒ‹: {price} á‰¥áˆ­ ({negotiable_text})\n"
      
       if category == 'áˆ˜áŠªáŠ“':
           if car_type: full_desc += f"ðŸš— áŠ á‹­áŠá‰µ: {car_type}\n"
           if fuel_type: full_desc += f"â›½ áŠá‹³áŒ…: {fuel_type}\n"
           if transmission: full_desc += f"âš™ï¸ áˆ›áˆ­áˆ½: {transmission}\n"
           if mileage: full_desc += f"ðŸ›£ï¸ áŠªáˆŽáˆœá‰µáˆ­: {mileage} KM\n"
           if condition: full_desc += f"ðŸ“Š áˆáŠ”á‰³: {condition}\n"
       else:
           if house_type: full_desc += f"ðŸ  áŠ á‹­áŠá‰µ: {house_type}\n"
           if bedrooms: full_desc += f"ðŸ›ï¸ áˆ˜áŠá‰³: {bedrooms}\n"
           if bathrooms: full_desc += f"ðŸ› áˆ˜á‰³áŒ á‰¢á‹«: {bathrooms}\n"
           if parking: full_desc += f"ðŸš— á“áˆ­áŠªáŠ•áŒ: {parking}\n"
           if house_condition: full_desc += f"ðŸ“Š áˆáŠ”á‰³: {house_condition}\n"
      
       full_desc += f"ðŸ“ áˆ˜áŒáˆˆáŒ«: {description}\n"
       full_desc += f"ðŸ“ž áˆµáˆáŠ­: {phone}\n"
       if telegram_user: full_desc += f"ðŸ“± Telegram: {telegram_user}\n"

       req_id = add_listing(
           user_chat_id=int(user_id) if str(user_id).isdigit() else 0,
           user_name="WebApp User",
           req_type="SELL",
           main_category=category,
           sub_category=car_type if category == 'áˆ˜áŠªáŠ“' else house_type,
           action_type="áˆ˜áˆ¸áŒ¥",
           property_type="",
           description=full_desc,
           price=str(price),
           phone=str(phone),
           extra_data={
               'fuel_type': fuel_type, 'transmission': transmission, 'mileage': mileage,
               'condition': condition or house_condition, 'bedrooms': bedrooms,
               'bathrooms': bathrooms, 'parking': parking, 'house_type': house_type,
               'car_type': car_type, 'negotiable': negotiable, 'urgent_sale': urgent_sale,
               'telegram_user': telegram_user
           },
           photos=photos
       )

       if req_id:
           logger.info(f"âœ… Seller listing saved ID={req_id}")
           notification_text = (
               f"ðŸ›ï¸ **áŠ á‹²áˆµ á‹¨áˆ½á‹«áŒ­ áˆ›áˆµá‰³á‹ˆá‰‚á‹« (#ADK-{req_id})**\n\n"
               f"{full_desc}"
           )
           _send_notification_safe(notification_text, req_id, int(user_id))
           return jsonify({"status": "success", "req_id": req_id})
       else:
           return jsonify({"status": "error", "message": "Database á‹áˆµáŒ¥ áˆ›áˆµá‰€áˆ˜áŒ¥ áŠ áˆá‰°á‰»áˆˆáˆá¢"}), 500
   except Exception as e:
       logger.error(f"âŒ submit_listing error: {e}", exc_info=True)
       return jsonify({"status": "error", "message": f"Server Error: {str(e)}"}), 500

@web_app.route('/api/submit-request', methods=['POST'])
def submit_request():
   try:
       data = request.json or {}
       user_id = data.get('user_id')
       category = data.get('category', 'áˆ˜áŠªáŠ“')
       budget_min = data.get('budget_min', '')
       budget_max = data.get('budget_max', '')
       create_alert = data.get('create_alert', False)
       details = data.get('details', '')
       phone = data.get('phone', '')
       telegram_user = data.get('telegram_user', '')

       logger.info(f"ðŸ“¥ Buyer WebApp data: {data}")

       if not user_id or user_id == "unknown":
           return jsonify({"status": "error", "message": "User ID áŠ áˆá‰°áŒˆáŠ˜áˆá¢ Telegram á‹áˆµáŒ¥ áŠ­áˆá‰µá¢"}), 400

       budget_range = f"{budget_min} - {budget_max}" if budget_min and budget_max else (budget_min or budget_max or "á‹«áˆá‰°áŒˆáˆˆáŒ¸")

       full_desc = (
           f"ðŸ’° á‰ áŒ€á‰µ áŠ­áˆáˆ: {budget_range} á‰¥áˆ­\n"
           f"ðŸ“ á‹áˆ­á‹áˆ­: {details}\n"
           f"ðŸ“ž áˆµáˆáŠ­: {phone}\n"
       )
       if telegram_user: full_desc += f"ðŸ“± Telegram: {telegram_user}\n"

       req_id = add_listing(
           user_chat_id=int(user_id) if str(user_id).isdigit() else 0,
           user_name="WebApp User",
           req_type="BUY",
           main_category=category,
           sub_category="",
           action_type="áˆ˜áŒá‹›á‰µ",
           property_type="",
           description=full_desc,
           price=budget_range,
           phone=str(phone),
           extra_data={
               'budget_min': budget_min, 'budget_max': budget_max,
               'create_alert': create_alert, 'telegram_user': telegram_user
           }
       )

       if req_id:
           logger.info(f"âœ… Buyer request saved ID={req_id}")
           notification_text = (
               f"ðŸ”” **áŠ á‹²áˆµ á‹¨{category} áŒ¥á‹«á‰„ (#ADK-{req_id})**\n\n"
               f"{full_desc}"
           )
           _send_notification_safe(notification_text, req_id, int(user_id))

           if create_alert and str(user_id).isdigit():
               save_search_alert(int(user_id), category, budget_min, budget_max)

           return jsonify({"status": "success", "req_id": req_id})
       else:
           return jsonify({"status": "error", "message": "Database á‹áˆµáŒ¥ áˆ›áˆµá‰€áˆ˜áŒ¥ áŠ áˆá‰°á‰»áˆˆáˆá¢"}), 500
   except Exception as e:
       logger.error(f"âŒ submit_request error: {e}", exc_info=True)
       return jsonify({"status": "error", "message": f"Server Error: {str(e)}"}), 500

def run_flask():
   port = int(os.environ.get("PORT", 8080))
   web_app.run(host="0.0.0.0", port=port, use_reloader=False)
# ==============================================================================
# 3. DATABASE CONNECTION & INITIALIZATION
# ==============================================================================

def get_db_connection():
   if DATABASE_URL:
       cleaned_url = DATABASE_URL.strip().strip('"').strip("'")
       if cleaned_url.startswith("postgres://"):
           cleaned_url = cleaned_url.replace("postgres://", "postgresql://", 1)
       conn = psycopg2.connect(cleaned_url, cursor_factory=RealDictCursor)
       conn.autocommit = True
       return conn
   else:
       conn = sqlite3.connect(DB_FILE, check_same_thread=False)
       conn.row_factory = sqlite3.Row
       return conn

def get_placeholder():
   return "%s" if DATABASE_URL else "?"

def init_db():
   conn = None
   try:
       conn = get_db_connection()
       cursor = conn.cursor()

       if DATABASE_URL:
           cursor.execute("""
               CREATE TABLE IF NOT EXISTS listings (
                   id SERIAL PRIMARY KEY,
                   user_chat_id BIGINT NOT NULL,
                   user_name TEXT,
                   req_type TEXT NOT NULL,
                   main_category TEXT NOT NULL,
                   sub_category TEXT,
                   action_type TEXT,
                   property_type TEXT,
                   description TEXT NOT NULL,
                   price TEXT,
                   phone TEXT,
                   photo_id TEXT,
                   extra_data JSONB DEFAULT '{}',
                   status TEXT DEFAULT 'pending',
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
               );
               CREATE TABLE IF NOT EXISTS brokers (
                   id SERIAL PRIMARY KEY,
                   chat_id BIGINT NOT NULL UNIQUE,
                   full_name TEXT NOT NULL,
                   phone TEXT NOT NULL,
                   role_type TEXT NOT NULL,
                   national_id_photo TEXT,
                   sub_city TEXT NOT NULL,
                   rating REAL DEFAULT 5.0,
                   total_ratings INT DEFAULT 0,
                   notification_prefs JSONB DEFAULT '{"car": true, "house": true, "price_min": 0, "price_max": 999999999, "enabled": true}',
                   status TEXT DEFAULT 'pending',
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
               );
               CREATE TABLE IF NOT EXISTS ratings (
                   id SERIAL PRIMARY KEY,
                   broker_chat_id BIGINT NOT NULL,
                   user_chat_id BIGINT NOT NULL,
                   stars INT NOT NULL,
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
               );
               CREATE TABLE IF NOT EXISTS broker_offers (
                   id SERIAL PRIMARY KEY,
                   request_id INTEGER NOT NULL,
                   broker_id BIGINT NOT NULL,
                   description TEXT,
                   photo_id TEXT,
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
               );
               CREATE TABLE IF NOT EXISTS search_alerts (
                   id SERIAL PRIMARY KEY,
                   user_chat_id BIGINT NOT NULL,
                   main_category TEXT NOT NULL,
                   budget_min TEXT,
                   budget_max TEXT,
                   is_active BOOLEAN DEFAULT TRUE,
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
               );
               CREATE TABLE IF NOT EXISTS favorites (
                   id SERIAL PRIMARY KEY,
                   user_chat_id BIGINT NOT NULL,
                   listing_id INTEGER NOT NULL,
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                   UNIQUE(user_chat_id, listing_id)
               );
               CREATE TABLE IF NOT EXISTS listing_photos (
                   id SERIAL PRIMARY KEY,
                   listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
                   photo_id TEXT NOT NULL,
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
               );
           """)
       else:
           cursor.execute("""
               CREATE TABLE IF NOT EXISTS listings (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   user_chat_id INTEGER NOT NULL,
                   user_name TEXT,
                   req_type TEXT NOT NULL,
                   main_category TEXT NOT NULL,
                   sub_category TEXT,
                   action_type TEXT,
                   property_type TEXT,
                   description TEXT NOT NULL,
                   price TEXT,
                   phone TEXT,
                   photo_id TEXT,
                   extra_data TEXT DEFAULT '{}',
                   status TEXT DEFAULT 'pending',
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
               );
           """)
           cursor.execute("""
               CREATE TABLE IF NOT EXISTS brokers (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   chat_id INTEGER NOT NULL UNIQUE,
                   full_name TEXT NOT NULL,
                   phone TEXT NOT NULL,
                   role_type TEXT NOT NULL,
                   national_id_photo TEXT,
                   sub_city TEXT NOT NULL,
                   rating REAL DEFAULT 5.0,
                   total_ratings INTEGER DEFAULT 0,
                   notification_prefs TEXT DEFAULT '{"car": true, "house": true, "price_min": 0, "price_max": 999999999, "enabled": true}',
                   status TEXT DEFAULT 'pending',
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
               );
           """)
           cursor.execute("""
               CREATE TABLE IF NOT EXISTS ratings (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   broker_chat_id INTEGER NOT NULL,
                   user_chat_id INTEGER NOT NULL,
                   stars INTEGER NOT NULL,
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
               );
           """)
           cursor.execute("""
               CREATE TABLE IF NOT EXISTS broker_offers (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   request_id INTEGER NOT NULL,
                   broker_id INTEGER NOT NULL,
                   description TEXT,
                   photo_id TEXT,
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
               );
           """)
           cursor.execute("""
               CREATE TABLE IF NOT EXISTS search_alerts (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   user_chat_id INTEGER NOT NULL,
                   main_category TEXT NOT NULL,
                   budget_min TEXT,
                   budget_max TEXT,
                   is_active BOOLEAN DEFAULT 1,
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
               );
           """)
           cursor.execute("""
               CREATE TABLE IF NOT EXISTS favorites (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   user_chat_id INTEGER NOT NULL,
                   listing_id INTEGER NOT NULL,
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                   UNIQUE(user_chat_id, listing_id)
               );
           """)
           cursor.execute("""
               CREATE TABLE IF NOT EXISTS listing_photos (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   listing_id INTEGER NOT NULL,
                   photo_id TEXT NOT NULL,
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
               );
           """)
           conn.commit()

       # áŠ á‹²áˆµ columns áˆˆáŠá‰£áˆ­ á‹³á‰³á‰¤á‹
       try:
           if DATABASE_URL:
               cursor.execute("ALTER TABLE listings ADD COLUMN IF NOT EXISTS extra_data JSONB DEFAULT '{}';")
           else:
               try: cursor.execute("ALTER TABLE listings ADD COLUMN extra_data TEXT DEFAULT '{}';")
               except: pass
           if not DATABASE_URL: conn.commit()
       except Exception as alter_err:
           logger.warning(f"ALTER TABLE warning: {alter_err}")

       logger.info("âœ… Adika Database initialized successfully")
   except Exception as e:
       logger.error(f"âŒ Database initialization error: {e}")
       if conn and not DATABASE_URL:
           conn.rollback()
   finally:
       if conn:
           conn.close()
# ==============================================================================
# 4. DATABASE OPERATIONS
# ==============================================================================

import json

def add_listing(user_chat_id, user_name, req_type, main_category, sub_category,
               action_type, property_type, description, price=None, phone=None, 
               photo_id=None, extra_data=None, photos=None):
   conn = None
   try:
       conn = get_db_connection()
       cursor = conn.cursor()
       p = get_placeholder()

       # JSON serialization for extra_data
       if extra_data is None:
           extra_data = {}
       extra_json = json.dumps(extra_data, ensure_ascii=False) if not isinstance(extra_data, str) else extra_data

       # Ensure all required fields have values
       user_chat_id = int(user_chat_id) if user_chat_id else 0
       user_name = str(user_name or "User")
       req_type = str(req_type or "BUY")
       main_category = str(main_category or "áˆ˜áŠªáŠ“")
       sub_category = str(sub_category or "")
       action_type = str(action_type or "")
       property_type = str(property_type or "")
       description = str(description or "")
       price = str(price or "")
       phone = str(phone or "")
       photo_id = str(photo_id) if photo_id else None

       query = f"""
           INSERT INTO listings 
           (user_chat_id, user_name, req_type, main_category, sub_category, 
            action_type, property_type, description, price, phone, photo_id, extra_data, status)
           VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, 'pending')
       """
       params = (
           user_chat_id, user_name, req_type, main_category, 
           sub_category, action_type, property_type, 
           description, price, phone, photo_id,
           extra_json
       )

       logger.info(f"ðŸ“ Attempting to insert listing: user={user_chat_id}, type={req_type}, cat={main_category}")

       if DATABASE_URL:
           cursor.execute(query + " RETURNING id", params)
           row = cursor.fetchone()
           if row is None:
               logger.error("RETURNING id returned None")
               return None
           req_id = row["id"] if isinstance(row, dict) else row[0]
       else:
           cursor.execute(query, params)
           req_id = cursor.lastrowid
           conn.commit()

       logger.info(f"âœ… Listing inserted with ID: {req_id}")

       # Save photos if any
       if photos and req_id:
           logger.info(f"ðŸ“¸ Saving {len(photos)} photos for listing {req_id}")
           for photo in photos:
               try:
                   photo_str = str(photo)
                   cursor.execute(
                       f"INSERT INTO listing_photos (listing_id, photo_id) VALUES ({p}, {p})",
                       (req_id, photo_str)
                   )
               except Exception as pe:
                   logger.error(f"Failed to save photo for listing {req_id}: {pe}")
           
           if not DATABASE_URL:
               conn.commit()

       logger.info(f"âœ… Listing added successfully with ID: {req_id} (ADK-{req_id})")
       return req_id

   except Exception as e:
       logger.error(f"âŒ Add listing error: {e}", exc_info=True)
       if conn and not DATABASE_URL:
           try:
               conn.rollback()
           except:
               pass
       return None
   finally:
       if conn:
           try:
               conn.close()
           except:
               pass


def get_listing_by_id(listing_id: int):
   conn = None
   try:
       conn = get_db_connection()
       cursor = conn.cursor()
       p = get_placeholder()
       
       cursor.execute(f"SELECT * FROM listings WHERE id = {p}", (listing_id,))
       row = cursor.fetchone()
       
       if not row:
           return None
           
       result = dict(row) if isinstance(row, dict) else dict(zip([c[0] for c in cursor.description], row))
       
       # Parse extra_data JSON
       if 'extra_data' in result and isinstance(result['extra_data'], str):
           try:
               result['extra_data'] = json.loads(result['extra_data'])
           except:
               result['extra_data'] = {}
       
       # Load photos
       try:
           cursor.execute(f"SELECT photo_id FROM listing_photos WHERE listing_id = {p}", (listing_id,))
           photo_rows = cursor.fetchall()
           result['photos'] = [dict(r)['photo_id'] if isinstance(r, dict) else r[0] for r in photo_rows]
       except Exception as e:
           logger.warning(f"Could not load photos for listing {listing_id}: {e}")
           result['photos'] = []
       
       return result
   except Exception as e:
       logger.error(f"Get listing by id error: {e}")
       return None
   finally:
       if conn:
           try:
               conn.close()
           except:
               pass


def get_listings_by_category(limit=10, offset=0, req_type=None):
   conn = None
   try:
       conn = get_db_connection()
       cursor = conn.cursor()
       p = get_placeholder()

       if req_type:
           query = f"""
               SELECT * FROM listings 
               WHERE status = 'pending' AND req_type = {p} 
               ORDER BY created_at DESC 
               LIMIT {p} OFFSET {p}
           """
           cursor.execute(query, (req_type, limit, offset))
       else:
           query = f"""
               SELECT * FROM listings 
               WHERE status = 'pending' 
               ORDER BY created_at DESC 
               LIMIT {p} OFFSET {p}
           """
           cursor.execute(query, (limit, offset))

       rows = cursor.fetchall()
       results = []
       for row in rows:
           item = dict(row) if isinstance(row, dict) else dict(zip([c[0] for c in cursor.description], row))
           # Parse extra_data
           if 'extra_data' in item and isinstance(item['extra_data'], str):
               try:
                   item['extra_data'] = json.loads(item['extra_data'])
               except:
                   item['extra_data'] = {}
           results.append(item)
       
       logger.info(f"ðŸ“‹ Retrieved {len(results)} listings (type={req_type})")
       return results
   except Exception as e:
       logger.error(f"Get listings error: {e}")
       return []
   finally:
       if conn:
           try:
               conn.close()
           except:
               pass


def count_listings(req_type=None):
   conn = None
   try:
       conn = get_db_connection()
       cursor = conn.cursor()
       if req_type:
           p = get_placeholder()
           cursor.execute(f"SELECT COUNT(*) as cnt FROM listings WHERE status = 'pending' AND req_type = {p}", (req_type,))
       else:
           cursor.execute("SELECT COUNT(*) as cnt FROM listings WHERE status = 'pending'")
       row = cursor.fetchone()
       if isinstance(row, dict):
           return row.get('cnt', 0)
       else:
           return row[0] if row else 0
   except Exception as e:
       logger.error(f"Count listings error: {e}")
       return 0
   finally:
       if conn:
           try:
               conn.close()
           except:
               pass


def update_listing_status(req_id: int, status: str) -> bool:
   conn = None
   try:
       conn = get_db_connection()
       cursor = conn.cursor()
       p = get_placeholder()
       cursor.execute(f"UPDATE listings SET status = {p} WHERE id = {p}", (status, req_id))
       if not DATABASE_URL:
           conn.commit()
       logger.info(f"âœ… Listing {req_id} status updated to {status}")
       return True
   except Exception as e:
       logger.error(f"Update listing error: {e}")
       return False
   finally:
       if conn:
           try:
               conn.close()
           except:
               pass


def get_public_marketplace_items(main_category=None, limit=10, offset=0):
   conn = None
   try:
       conn = get_db_connection()
       cursor = conn.cursor()
       p = get_placeholder()

       if main_category:
           query = f"""
               SELECT * FROM listings 
               WHERE req_type = 'SELL' AND status = 'pending' AND main_category = {p}
               ORDER BY created_at DESC 
               LIMIT {p} OFFSET {p}
           """
           cursor.execute(query, (main_category, limit, offset))
       else:
           query = f"""
               SELECT * FROM listings 
               WHERE req_type = 'SELL' AND status = 'pending'
               ORDER BY created_at DESC 
               LIMIT {p} OFFSET {p}
           """
           cursor.execute(query, (limit, offset))

       rows = cursor.fetchall()
       results = []
       for row in rows:
           item = dict(row) if isinstance(row, dict) else dict(zip([c[0] for c in cursor.description], row))
           # Parse extra_data
           if 'extra_data' in item and isinstance(item['extra_data'], str):
               try:
                   item['extra_data'] = json.loads(item['extra_data'])
               except:
                   item['extra_data'] = {}
           # Load photos
           try:
               cursor.execute(f"SELECT photo_id FROM listing_photos WHERE listing_id = {p}", (item['id'],))
               photo_rows = cursor.fetchall()
               item['photos'] = [dict(r)['photo_id'] if isinstance(r, dict) else r[0] for r in photo_rows]
           except Exception:
               item['photos'] = []
           results.append(item)
       
       logger.info(f"ðŸ›ï¸ Retrieved {len(results)} marketplace items")
       return results
   except Exception as e:
       logger.error(f"Get public marketplace items error: {e}")
       return []
   finally:
       if conn:
           try:
               conn.close()
           except:
               pass


# ========== BROKER OPERATIONS ==========

def add_broker(chat_id, full_name, phone, role_type, national_id_photo, sub_city):
   conn = None
   try:
       conn = get_db_connection()
       cursor = conn.cursor()
       p = get_placeholder()

       cursor.execute(f"SELECT id FROM brokers WHERE chat_id = {p}", (chat_id,))
       existing = cursor.fetchone()

       default_prefs = json.dumps({"car": True, "house": True, "price_min": 0, "price_max": 999999999, "enabled": True}, ensure_ascii=False)

       if existing:
           if DATABASE_URL:
               query = f"""
                   UPDATE brokers 
                   SET full_name = {p}, phone = {p}, role_type = {p},
                       national_id_photo = {p}, sub_city = {p}, status = 'pending'
                   WHERE chat_id = {p} RETURNING id
               """
               cursor.execute(query, (full_name, phone, role_type, national_id_photo, sub_city, chat_id))
               row = cursor.fetchone()
               broker_id = row["id"] if isinstance(row, dict) else row[0]
           else:
               query = """
                   UPDATE brokers 
                   SET full_name = ?, phone = ?, role_type = ?,
                       national_id_photo = ?, sub_city = ?, status = 'pending'
                   WHERE chat_id = ?
               """
               cursor.execute(query, (full_name, phone, role_type, national_id_photo, sub_city, chat_id))
               broker_id = existing[0] if not isinstance(existing, dict) else existing["id"]
               conn.commit()
       else:
           if DATABASE_URL:
               query = f"""
                   INSERT INTO brokers (chat_id, full_name, phone, role_type, national_id_photo, sub_city, notification_prefs, status)
                   VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, 'pending') RETURNING id
               """
               cursor.execute(query, (chat_id, full_name, phone, role_type, national_id_photo, sub_city, default_prefs))
               row = cursor.fetchone()
               broker_id = row["id"] if isinstance(row, dict) else row[0]
           else:
               query = """
                   INSERT INTO brokers (chat_id, full_name, phone, role_type, national_id_photo, sub_city, notification_prefs, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
               """
               cursor.execute(query, (chat_id, full_name, phone, role_type, national_id_photo, sub_city, default_prefs))
               broker_id = cursor.lastrowid
               conn.commit()

       logger.info(f"âœ… Broker registered: {broker_id}")
       return broker_id
   except Exception as e:
       logger.error(f"Add broker error: {e}")
       return None
   finally:
       if conn:
           try:
               conn.close()
           except:
               pass


def get_broker(chat_id: int):
   conn = None
   try:
       conn = get_db_connection()
       cursor = conn.cursor()
       p = get_placeholder()
       cursor.execute(f"SELECT * FROM brokers WHERE chat_id = {p}", (chat_id,))
       row = cursor.fetchone()
       if row:
           return dict(row) if isinstance(row, dict) else dict(zip([c[0] for c in cursor.description], row))
       return None
   except Exception as e:
       logger.error(f"Get broker error: {e}")
       return None
   finally:
       if conn:
           try:
               conn.close()
           except:
               pass


def update_broker_status(chat_id: int, status: str) -> bool:
   conn = None
   try:
       conn = get_db_connection()
       cursor = conn.cursor()
       p = get_placeholder()
       cursor.execute(f"UPDATE brokers SET status = {p} WHERE chat_id = {p}", (status.lower(), chat_id))
       if not DATABASE_URL:
           conn.commit()
       return True
   except Exception as e:
       logger.error(f"Update broker status error: {e}")
       return False
   finally:
       if conn:
           try:
               conn.close()
           except:
               pass


def update_broker_notification_prefs(chat_id: int, prefs: dict) -> bool:
   conn = None
   try:
       conn = get_db_connection()
       cursor = conn.cursor()
       p = get_placeholder()
       prefs_json = json.dumps(prefs, ensure_ascii=False)
       cursor.execute(f"UPDATE brokers SET notification_prefs = {p} WHERE chat_id = {p}", (prefs_json, chat_id))
       if not DATABASE_URL:
           conn.commit()
       return True
   except Exception as e:
       logger.error(f"Update broker notification prefs error: {e}")
       return False
   finally:
       if conn:
           try:
               conn.close()
           except:
               pass


def get_approved_brokers():
   conn = None
   try:
       conn = get_db_connection()
       cursor = conn.cursor()
       cursor.execute("SELECT * FROM brokers WHERE status = 'approved'")
       rows = cursor.fetchall()
       results = []
       for row in rows:
           broker = dict(row) if isinstance(row, dict) else dict(zip([c[0] for c in cursor.description], row))
           # Parse notification_prefs
           if 'notification_prefs' in broker and isinstance(broker['notification_prefs'], str):
               try:
                   broker['notification_prefs'] = json.loads(broker['notification_prefs'])
               except:
                   broker['notification_prefs'] = {"car": True, "house": True, "enabled": True}
           results.append(broker)
       
       logger.info(f"ðŸ‘¥ Retrieved {len(results)} approved brokers")
       return results
   except Exception as e:
       logger.error(f"Get approved brokers error: {e}")
       return []
   finally:
       if conn:
           try:
               conn.close()
           except:
               pass


def get_approved_brokers_directory(sub_city=None):
   conn = None
   try:
       conn = get_db_connection()
       cursor = conn.cursor()
       p = get_placeholder()

       if sub_city and sub_city != "áˆáˆ‰áˆ":
           query = f"""
               SELECT full_name, phone, role_type, sub_city, rating, total_ratings 
               FROM brokers WHERE status = 'approved' AND sub_city = {p}
               ORDER BY rating DESC
           """
           cursor.execute(query, (sub_city,))
       else:
           query = """
               SELECT full_name, phone, role_type, sub_city, rating, total_ratings 
               FROM brokers WHERE status = 'approved' ORDER BY rating DESC
           """
           cursor.execute(query)

       rows = cursor.fetchall()
       return [dict(row) if isinstance(row, dict) else dict(zip([c[0] for c in cursor.description], row)) for row in rows]
   except Exception as e:
       logger.error(f"Get approved brokers directory error: {e}")
       return []
   finally:
       if conn:
           try:
               conn.close()
           except:
               pass


# ========== BROKER OFFERS ==========

def save_broker_offer(request_id: int, broker_id: int, description: str, photo_id: str = None) -> bool:
   conn = None
   try:
       conn = get_db_connection()
       cursor = conn.cursor()
       p = get_placeholder()
       cursor.execute(f"""
           INSERT INTO broker_offers (request_id, broker_id, description, photo_id)
           VALUES ({p}, {p}, {p}, {p})
       """, (request_id, broker_id, description, photo_id))
       if not DATABASE_URL:
           conn.commit()
       return True
   except Exception as e:
       logger.error(f"Save broker offer error: {e}")
       return False
   finally:
       if conn:
           try:
               conn.close()
           except:
               pass


# ========== RATINGS ==========

def add_broker_rating(broker_chat_id, user_chat_id, stars):
   conn = None
   try:
       conn = get_db_connection()
       cursor = conn.cursor()
       p = get_placeholder()

       cursor.execute(
           f"INSERT INTO ratings (broker_chat_id, user_chat_id, stars) VALUES ({p}, {p}, {p})",
           (broker_chat_id, user_chat_id, stars)
       )

       cursor.execute(
           f"SELECT AVG(stars) as avg_stars, COUNT(*) as total_count FROM ratings WHERE broker_chat_id = {p}",
           (broker_chat_id,)
       )
       result = cursor.fetchone()
       
       if isinstance(result, dict):
           avg_stars = result.get('avg_stars', 5.0)
           total_count = result.get('total_count', 0)
       else:
           avg_stars = result[0] if result[0] else 5.0
           total_count = result[1] if result[1] else 0

       cursor.execute(
           f"UPDATE brokers SET rating = {p}, total_ratings = {p} WHERE chat_id = {p}",
           (round(float(avg_stars), 1), total_count, broker_chat_id)
       )

       if not DATABASE_URL:
           conn.commit()
       return True
   except Exception as e:
       logger.error(f"Add broker rating error: {e}")
       return False
   finally:
       if conn:
           try:
               conn.close()
           except:
               pass


# ========== SEARCH ALERTS ==========

def save_search_alert(user_chat_id: int, main_category: str, budget_min: str, budget_max: str) -> int:
   conn = None
   try:
       conn = get_db_connection()
       cursor = conn.cursor()
       p = get_placeholder()
       cursor.execute(f"""
           INSERT INTO search_alerts (user_chat_id, main_category, budget_min, budget_max)
           VALUES ({p}, {p}, {p}, {p})
       """, (user_chat_id, main_category, budget_min or "", budget_max or ""))
       
       if DATABASE_URL:
           # For PostgreSQL, we need RETURNING
           cursor.execute("SELECT lastval()")
           row = cursor.fetchone()
           alert_id = row[0] if not isinstance(row, dict) else list(row.values())[0]
       else:
           alert_id = cursor.lastrowid
           conn.commit()
       
       logger.info(f"âœ… Search alert saved for user {user_chat_id}")
       return alert_id or 0
   except Exception as e:
       logger.error(f"Save search alert error: {e}")
       return 0
   finally:
       if conn:
           try:
               conn.close()
           except:
               pass


def get_matching_alerts(main_category: str, price: str) -> list:
   """áŠ¨áŠ á‹²áˆµ áˆ›áˆµá‰³á‹ˆá‰‚á‹« áŒ‹áˆ­ á‹¨áˆšá‹›áˆ˜á‹± Search Alerts á‹«áŒáŠ™"""
   conn = None
   try:
       conn = get_db_connection()
       cursor = conn.cursor()
       p = get_placeholder()
       query = f"""
           SELECT * FROM search_alerts 
           WHERE is_active = TRUE AND main_category = {p}
           ORDER BY created_at DESC
       """
       cursor.execute(query, (main_category,))
       rows = cursor.fetchall()
       
       matching = []
       try:
           price_num = float(price) if price else 0
       except (ValueError, TypeError):
           price_num = 0
       
       for row in rows:
           alert = dict(row) if isinstance(row, dict) else dict(zip([c[0] for c in cursor.description], row))
           try:
               alert_min = float(alert.get('budget_min', 0) or 0)
               alert_max = float(alert.get('budget_max', 999999999) or 999999999)
               if alert_min <= price_num <= alert_max:
                   matching.append(alert)
           except (ValueError, TypeError):
               matching.append(alert)
       
       return matching
   except Exception as e:
       logger.error(f"Get matching alerts error: {e}")
       return []
   finally:
       if conn:
           try:
               conn.close()
           except:
               pass


# ========== FAVORITES ==========

def add_favorite(user_chat_id: int, listing_id: int) -> bool:
   conn = None
   try:
       conn = get_db_connection()
       cursor = conn.cursor()
       p = get_placeholder()
       
       # Check if already exists
       cursor.execute(f"SELECT id FROM favorites WHERE user_chat_id = {p} AND listing_id = {p}", (user_chat_id, listing_id))
       if cursor.fetchone():
           return True  # Already favorited
       
       cursor.execute(f"""
           INSERT INTO favorites (user_chat_id, listing_id)
           VALUES ({p}, {p})
       """, (user_chat_id, listing_id))
       if not DATABASE_URL:
           conn.commit()
       return True
   except Exception as e:
       logger.error(f"Add favorite error: {e}")
       return False
   finally:
       if conn:
           try:
               conn.close()
           except:
               pass


def remove_favorite(user_chat_id: int, listing_id: int) -> bool:
   conn = None
   try:
       conn = get_db_connection()
       cursor = conn.cursor()
       p = get_placeholder()
       cursor.execute(f"DELETE FROM favorites WHERE user_chat_id = {p} AND listing_id = {p}", (user_chat_id, listing_id))
       if not DATABASE_URL:
           conn.commit()
       return True
   except Exception as e:
       logger.error(f"Remove favorite error: {e}")
       return False
   finally:
       if conn:
           try:
               conn.close()
           except:
               pass


def get_user_favorites(user_chat_id: int, limit=20) -> list:
   conn = None
   try:
       conn = get_db_connection()
       cursor = conn.cursor()
       p = get_placeholder()
       query = f"""
           SELECT l.* FROM listings l
           INNER JOIN favorites f ON l.id = f.listing_id
           WHERE f.user_chat_id = {p} AND l.status = 'pending'
           ORDER BY f.created_at DESC
           LIMIT {p}
       """
       cursor.execute(query, (user_chat_id, limit))
       rows = cursor.fetchall()
       results = []
       for row in rows:
           item = dict(row) if isinstance(row, dict) else dict(zip([c[0] for c in cursor.description], row))
           if 'extra_data' in item and isinstance(item['extra_data'], str):
               try:
                   item['extra_data'] = json.loads(item['extra_data'])
               except:
                   item['extra_data'] = {}
           # Load photos
           try:
               cursor.execute(f"SELECT photo_id FROM listing_photos WHERE listing_id = {p}", (item['id'],))
               photo_rows = cursor.fetchall()
               item['photos'] = [dict(r)['photo_id'] if isinstance(r, dict) else r[0] for r in photo_rows]
           except Exception:
               item['photos'] = []
           results.append(item)
       return results
   except Exception as e:
       logger.error(f"Get user favorites error: {e}")
       return []
   finally:
       if conn:
           try:
               conn.close()
           except:
               pass


def is_favorite(user_chat_id: int, listing_id: int) -> bool:
   conn = None
   try:
       conn = get_db_connection()
       cursor = conn.cursor()
       p = get_placeholder()
       cursor.execute(f"SELECT 1 FROM favorites WHERE user_chat_id = {p} AND listing_id = {p}", (user_chat_id, listing_id))
       return cursor.fetchone() is not None
   except Exception as e:
       logger.error(f"Check favorite error: {e}")
       return False
   finally:
       if conn:
           try:
               conn.close()
           except:
               pass


# ========== SIMILAR LISTINGS ==========

def get_similar_listings(listing_id: int, limit=5) -> list:
   """á‰°áˆ˜áˆ³áˆ³á‹­ áˆá‹µá‰¥ áŠ¥áŠ“ á‹¨á‹‹áŒ‹ áŠ­áˆáˆ á‹«áˆ‹á‰¸á‹ áˆ›áˆµá‰³á‹ˆá‰‚á‹«á‹Žá‰½áŠ• á‹«áŒáŠ™"""
   conn = None
   try:
       listing = get_listing_by_id(listing_id)
       if not listing:
           return []
       
       conn = get_db_connection()
       cursor = conn.cursor()
       p = get_placeholder()
       
       main_cat = listing.get('main_category', '')
       try:
           price = float(listing.get('price', 0) or 0)
       except (ValueError, TypeError):
           price = 0
       
       query = f"""
           SELECT * FROM listings 
           WHERE id != {p} AND status = 'pending' AND main_category = {p}
           ORDER BY created_at DESC
           LIMIT {p}
       """
       cursor.execute(query, (listing_id, main_cat, limit))
       rows = cursor.fetchall()
       return [dict(row) if isinstance(row, dict) else dict(zip([c[0] for c in cursor.description], row)) for row in rows]
   except Exception as e:
       logger.error(f"Get similar listings error: {e}")
       return []
   finally:
       if conn:
           try:
               conn.close()
           except:
               pass
# ==============================================================================
# 5. CONSTANTS & KEYBOARDS
# ==============================================================================
MAIN_KEYBOARD = [
   ["ðŸ” áˆ˜áŒá‹›á‰µ / áˆ˜áŠ¨áˆ«á‹¨á‰µ", "ðŸ“¢ áˆ˜áˆ¸áŒ¥ / áˆ›áŠ¨áˆ«á‹¨á‰µ"],
   ["ðŸ›ï¸ á‹¨áŒˆá‰ á‹« á‰¦á‰³ (á‹¨áˆšáˆ¸áŒ¡)", "ðŸ“‹ á‹¨áˆáˆ‹áŒŠá‹Žá‰½ á‹áˆ­á‹áˆ­"],
   ["ðŸ‘¥ á‹¨á‹°áˆ‹áˆŽá‰½/áŠ á‰…áˆ«á‰¢á‹Žá‰½ áˆ›á‹áŒ«", "ðŸ“ áŠ¥áŠ•á‹° áŠ á‰…áˆ«á‰¢/á‹°áˆ‹áˆ‹ áˆ˜áˆ˜á‹áŒˆá‰¥"],
   ["ðŸ“ž á‹µáŒ‹á", "âš™ï¸ á‹¨áˆ›áˆ³á‹ˆá‰‚á‹« áˆáˆ­áŒ«"],
   ["ðŸ  á‹‹áŠ“ áŒˆáŒ½"]
]

SUB_CITIES = [
   "á‰¦áˆŒ", "á‹¨áŠ«", "áŠ áˆ«á‹³", "áˆá‹°á‰³",
   "á‰‚áˆ­á‰†áˆµ", "áŠ á‹²áˆµ áŠ¨á‰°áˆ›", "áŠ•á‹áˆµ áˆµáˆáŠ­ áˆ‹áá‰¶",
   "áŠ®áˆáŒ á‰€áˆ«áŠ’á‹®", "áŠ á‰ƒá‰‚ á‰ƒáˆŠá‰²", "áŒ‰áˆŒáˆŒ", "áˆ‹áˆá‰ áˆ­á‰µ/á‹¨áŠ«"
]

CAR_SUB_CATEGORIES = ["ðŸš— á‹¨á‰¤á‰µ áˆ˜áŠªáŠ“", "ðŸšš á‹¨áˆ¥áˆ« áˆ˜áŠªáŠ“", "ðŸšœ áŠ¨á‰£á‹µ á‰°áˆ½áŠ¨áˆ­áŠ«áˆª/áˆ›áˆ½áŠ•"]
HOUSE_TYPES = ["ðŸ¡ á‰ªáˆ‹", "ðŸ¢ áŠ á“áˆ­á‰³áˆ›", "ðŸ¢ áŠ®áŠ•á‹¶áˆšáŠ’á‹¨áˆ", "ðŸ¢ áˆªáˆ áŠ¥áˆµá‰´á‰µ", "ðŸžï¸ áˆ˜áˆ¬á‰µ/á‰¦á‰³"]
PROPERTY_TYPES = ["ðŸ  áˆ˜áŠ–áˆªá‹« á‰¤á‰µ", "ðŸ¢ á‹¨áˆ¥áˆ« á‰¦á‰³ / áŠ•áŒá‹µ"]
FUEL_TYPES = ["â›½ á‰¤áŠ•á‹šáŠ•", "ðŸ›¢ï¸ áŠ“ááŒ£", "âš¡ áŠ¤áˆŒáŠ­á‰µáˆªáŠ­", "ðŸ”‹ áˆ€á‹­á‰¥áˆªá‹µ"]
TRANSMISSION_TYPES = ["ðŸ•¹ï¸ áˆ›áŠ•á‹‹áˆ", "ðŸ¤– áŠ¦á‰¶áˆ›á‰²áŠ­"]
CONDITIONS = ["ðŸ†• áŠ á‹²áˆµ", "âœ… á‹«áŒˆáˆˆáŒˆáˆˆ", "ðŸ”§ áŒ¥áŒˆáŠ“ á‹¨áˆšáˆáˆáŒ"]
# ==============================================================================
# 6. HELPER FUNCTIONS
# ==============================================================================

def validate_phone(phone: str) -> bool:
    phone = phone.replace(' ', '').replace('-', '')
    pattern = r'^(09|07|01)\d{8}$|^\+251(9|7|1)\d{8}$'
    return bool(re.match(pattern, phone))

def validate_price(price: str) -> bool:
    price = price.replace(',', '').replace(' ', '')
    return price.isdigit()

def format_buyer_card(req: dict) -> str:
    req_id = req.get('id', 'N/A')
    main_cat = req.get('main_category', '')
    action_type = req.get('action_type', '')
    sub_cat = req.get('sub_category', 'á‹«áˆá‰°áŒ á‰€áˆ°')
    prop_type = req.get('property_type', 'á‹«áˆá‰°áŒ á‰€áˆ°')
    desc = req.get('description', '')
    phone = req.get('phone', 'áˆ˜áˆ¨áŒƒá‹ áŠ áˆá‰°á‹«á‹«á‹˜áˆ')

    icon = "ðŸš—" if main_cat in ["áˆ˜áŠªáŠ“", "car", "CAR"] else "ðŸ "

    return (
        f"{icon} **[áˆáˆ‹áŒŠ - #ADK-{req_id}]**\n"
        f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
        f"ðŸ“Œ **á‹˜áˆ­áá¦** {main_cat} ({action_type})\n"
        f"ðŸ·ï¸ **á‹“á‹­áŠá‰µá¦** {sub_cat} | {prop_type}\n"
        f"ðŸ“ **á‹áˆ­á‹áˆ­ ááˆ‹áŒŽá‰µá¦**\n_{desc}_\n\n"
        f"ðŸ“ž **á‹¨áˆáˆ‹áŒŠá‹ áˆµáˆáŠ­á¦** `{phone}`\n"
        f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
        f"ðŸ’¡ *áŠ¨á‰³á‰½ á‹«áˆ‰á‰µáŠ• áŠ á‹áˆ«áˆ®á‰½ á‹­áŒ á‰€áˆ™á¢*"
    )

def format_seller_card(item: dict) -> str:
    item_id = item.get('id', 'N/A')
    main_cat = item.get('main_category', '')
    action_type = item.get('action_type', '')
    sub_cat = item.get('sub_category', '-')
    desc = item.get('description', '')
    price = item.get('price', 'á‰ á‹µáˆ­á‹µáˆ­')
    phone = item.get('phone', '-')
    
    extra_data = item.get('extra_data', {})
    if isinstance(extra_data, str):
        try: extra_data = json.loads(extra_data)
        except: extra_data = {}
    
    is_urgent = extra_data.get('urgent_sale', False)
    is_negotiable = extra_data.get('negotiable', True)

    icon = "ðŸš—" if main_cat in ["áˆ˜áŠªáŠ“", "car", "CAR"] else "ðŸ "
    tag = "ðŸ”´ áˆˆáˆ½á‹«áŒ­" if action_type in ["áˆ˜áˆ¸áŒ¥", "SELL"] else "ðŸ”µ áˆˆáŠªáˆ«á‹­"
    urgent_badge = "âš¡ **áŠ áˆµá‰¸áŠ³á‹­ áˆ½á‹«áŒ­!** " if is_urgent else ""
    negotiable_text = "âœ… á‹¨áˆšá‹°áˆ«á‹°áˆ­" if is_negotiable else "âŒ á‹¨áˆ›á‹­á‹°áˆ«á‹°áˆ­"

    return (
        f"{icon} **[áˆˆáŒˆá‰ á‹« á‹¨á‰€áˆ¨á‰  - #ADK-{item_id}]** {tag} {urgent_badge}\n"
        f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
        f"ðŸ“¦ **áŠ á‹­áŠá‰µá¦** {main_cat} ({sub_cat})\n"
        f"ðŸ’° **á‹‹áŒ‹á¦** `{price}` ({negotiable_text})\n\n"
        f"ðŸ“‹ **áˆ˜áŒáˆˆáŒ«á¦**\n_{desc}_\n\n"
        f"ðŸ“ž **áˆµáˆáŠ­á¦** `{phone}`\n"
        f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
        f"âœ¨ *áˆˆá‰ áˆˆáŒ  áˆ˜áˆ¨áŒƒ áŠ¨á‰³á‰½ á‹«áˆ‰á‰µáŠ• á‰áˆáŽá‰½ á‹­áŒ á‰€áˆ™á¢*"
    )

def format_broker_profile(b: dict) -> str:
    stars = "â­" * int(float(b.get('rating', 5)))
    return (
        f"ðŸ‘¤ **áˆµáˆá¦** {b.get('full_name')}\n"
        f"ðŸŽ­ **áˆšáŠ“á¦** {b.get('role_type')}\n"
        f"ðŸ“ **áŠ­ááˆˆ áŠ¨á‰°áˆ›á¦** {b.get('sub_city')}\n"
        f"ðŸ“ž **áˆµáˆáŠ­á¦** `{b.get('phone')}`\n"
        f"â­ **á‹°áˆ¨áŒƒá¦** {b.get('rating', 5.0)}/5.0 ({b.get('total_ratings', 0)} áŒáˆáŒˆáˆ›á‹Žá‰½) {stars}\n"
        f"â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€"
    )

def get_nav_buttons(back_callback: str = None) -> list:
    buttons = []
    if back_callback:
        buttons.append(InlineKeyboardButton("â¬…ï¸ á‰°áˆ˜áˆˆáˆµ", callback_data=back_callback))
    buttons.append(InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home"))
    return buttons

def build_request_keyboard(req_id: int, user_id: int) -> InlineKeyboardMarkup:
    """áˆˆáˆáˆ‹áŒŠ áŒ¥á‹«á‰„á‹Žá‰½ (Buyer Requests)"""
    keyboard = [
        [
            InlineKeyboardButton("âœ… áŠ áˆˆáŠ", callback_data=f"have_item_{req_id}_{user_id}"),
            InlineKeyboardButton("â­ï¸ á‹­áˆˆáˆáŠ", callback_data=f"nohave_item_{req_id}")
        ],
        get_nav_buttons("flow_home")
    ]
    return InlineKeyboardMarkup(keyboard)

def build_seller_card_keyboard(item_id: int, owner_id: int, current_user_id: int, phone: str = "") -> InlineKeyboardMarkup:
    """áˆˆáˆ»áŒ­ áˆ›áˆµá‰³á‹ˆá‰‚á‹«á‹Žá‰½ (Seller Listings) - á‹°áˆ‹áˆŽá‰½ + á‰£áˆˆá‰¤á‰µ"""
    keyboard = []

    # á‹°áˆ‹áˆ‹ á‰áˆáŽá‰½
    keyboard.append([
        InlineKeyboardButton("ðŸ¤ áŒˆá‹¢/á‰°áŠ¨áˆ«á‹­ áŠ áˆˆáŠ", callback_data=f"have_buyer_{item_id}_{owner_id}"),
        InlineKeyboardButton("ðŸ‘¤ áˆˆáˆ«áˆ´ áŠ¥áˆáˆáŒˆá‹‹áˆˆáˆ", callback_data=f"want_myself_{item_id}")
    ])

    # áˆµáˆáŠ­ á‰áˆá (áŠ«áˆˆ)
    if phone and not str(phone).startswith("@"):
        clean_phone = phone.replace(' ', '').replace('-', '')
        keyboard.append([InlineKeyboardButton(f"ðŸ“ž á‹°á‹áˆ {phone}", url=f"tel:{clean_phone}")])
    elif phone and str(phone).startswith("@"):
        username = phone.lstrip("@")
        keyboard.append([InlineKeyboardButton(f"ðŸ’¬ Telegram @{username}", url=f"https://t.me/{username}")])

    # á‰£áˆˆá‰¤á‰µ á‹ˆá‹­áˆ áŠ á‹µáˆšáŠ• á‰¥á‰»
    if current_user_id == owner_id or current_user_id == ADMIN_CHAT_ID_INT:
        keyboard.append([
            InlineKeyboardButton("âœ… á‰°áˆ¸áŒ§áˆ / á‰°áŠ¨áˆ«á‹­á‰·áˆ", callback_data=f"mark_sold_{item_id}"),
            InlineKeyboardButton("ðŸ—‘ï¸ áŠ áŒ¥á‹", callback_data=f"delete_req_{item_id}")
        ])

    keyboard.append(get_nav_buttons("flow_home"))
    return InlineKeyboardMarkup(keyboard)

async def notify_brokers(bot, message_text: str, req_id: int, buyer_id: int):
    """áˆˆá‰°áˆá‰€á‹± á‹°áˆ‹áˆŽá‰½ áˆ›áˆ³á‹ˆá‰‚á‹« áˆ˜áˆ‹áŠ­"""
    try:
        approved_brokers = get_approved_brokers()
        if not approved_brokers:
            logger.info("No approved brokers found to notify")
            return

        listing = get_listing_by_id(req_id)
        main_category = listing.get('main_category', '') if listing else ''
        
        sent_count = 0
        for broker in approved_brokers:
            try:
                b_id = broker.get('chat_id')
                if not b_id:
                    continue
                
                prefs = broker.get('notification_prefs', {})
                if isinstance(prefs, str):
                    try: 
                        prefs = json.loads(prefs)
                    except: 
                        prefs = {}
                
                if not prefs.get('enabled', True):
                    continue
                
                if main_category == 'áˆ˜áŠªáŠ“' and not prefs.get('car', True):
                    continue
                if main_category in ['á‰¤á‰µ', 'house'] and not prefs.get('house', True):
                    continue
                
                # áˆˆáˆáˆ‹áŒŠ áŒ¥á‹«á‰„á‹Žá‰½ á‰áˆá
                kbd = [[
                    InlineKeyboardButton("âœ… áŠ áˆˆáŠ", callback_data=f"have_item_{req_id}_{buyer_id}"),
                    InlineKeyboardButton("â­ï¸ á‹­áˆˆáˆáŠ", callback_data=f"nohave_item_{req_id}")
                ]]
                
                await bot.send_message(
                    chat_id=b_id,
                    text=message_text,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(kbd)
                )
                sent_count += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.error(f"Failed to send notification to broker {broker.get('chat_id')}: {e}")
        
        logger.info(f"âœ… Sent notifications to {sent_count}/{len(approved_brokers)} brokers for listing #ADK-{req_id}")
        
    except Exception as e:
        logger.error(f"âŒ notify_brokers error: {e}", exc_info=True)

# ==============================================================================
# 7. CONVERSATION STATES
# ==============================================================================

(
   # Buyer flow states (0-10 = 11 states)
   BUYER_MAIN, BUYER_ACTION, BUYER_SUB, BUYER_PROPERTY, BUYER_HTYPE,
   BUYER_DETAILS, BUYER_PHONE, BUYER_TELEGRAM_USER, BUYER_BUDGET_RANGE, 
   BUYER_ALERT, BUYER_ALERT_CHOICE,
   # Seller flow states (11-29 = 19 states)
   SELLER_MAIN, SELLER_ACTION, SELLER_SUB, SELLER_PROPERTY, SELLER_HTYPE,
   SELLER_DETAILS, SELLER_PRICE, SELLER_NEGOTIABLE, SELLER_URGENT, 
   SELLER_CONDITION, SELLER_FUEL, SELLER_TRANSMISSION, SELLER_MILEAGE,
   SELLER_BEDROOMS, SELLER_PARKING, SELLER_PHONE, SELLER_TELEGRAM_USER,
   SELLER_PHOTO, SELLER_HOUSE_CONDITION,
   # Broker states (30-34 = 5 states)
   BROKER_ROLE, BROKER_NAME, BROKER_PHONE, BROKER_SUBCITY, BROKER_NID_PHOTO,
   # Broker offer states (35-36 = 2 states)
   BROKER_OFFER_TEXT, BROKER_OFFER_PHOTO,
   # Extra state (37 = 1 state)
   NOTIFICATION_PREFS
) = range(38)
# ==============================================================================
# 8. START & HOME HANDLERS
# ==============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
   context.user_data.clear()
   welcome_text = (
       "ðŸ‘‹ **áŠ¥áŠ•áŠ³áŠ• á‹ˆá‹° Adika Marketplace á‰ á‹°áˆ…áŠ“ áˆ˜áŒ¡!**\n\n"
       "á‹¨áˆ€áŒˆáˆªá‰± á‰³áˆ‹á‰ á‹¨áˆ˜áŠªáŠ“á£ á‹¨á‰¤á‰µ áŠ¥áŠ“ á‹¨áŠ•á‰¥áˆ¨á‰µ áŒˆá‰ á‹« áˆ›á‹•áŠ¨áˆá¢\n\n"
       "áŠ¥á‰£áŠ­á‹ŽáŠ• áŠ¨á‰³á‰½ áŠ«áˆ‰á‰µ áŠ áˆ›áˆ«áŒ®á‰½ áŠ áŠ•á‹±áŠ• á‹­áˆáˆ¨áŒ¡á¦"
   )
   await update.message.reply_text(
       welcome_text,
       parse_mode="Markdown",
       reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
   )
   return ConversationHandler.END

async def go_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
   context.user_data.clear()
   welcome_text = "ðŸ‘‹ **á‹ˆá‹° á‹‹áŠ“ áŒˆáŒ½ á‰°áˆ˜áˆáˆ°á‹‹áˆ!**\n\náŠ¥á‰£áŠ­á‹ŽáŠ• áŠ áˆ›áˆ«áŒ­ á‹­áˆáˆ¨áŒ¡á¦"
   reply_markup = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)

   if update.message:
       await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=reply_markup)
   elif update.callback_query:
       query = update.callback_query
       await query.answer()
       try:
           await query.delete_message()
       except Exception:
           pass
       await context.bot.send_message(
           chat_id=update.effective_user.id,
           text=welcome_text,
           parse_mode="Markdown",
           reply_markup=reply_markup
       )
   return ConversationHandler.END

# ==============================================================================
# 9. BUYER FLOW
# ==============================================================================

async def buyer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
   context.user_data.clear()
   context.user_data['req_type'] = 'BUY'

   web_app_url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'adika-vrkk.onrender.com')}/buyer-form"

   keyboard = [
       [InlineKeyboardButton("ðŸŒ á‰ áŽáˆ­áˆ á‰ ááŒ¥áŠá‰µ áˆˆáˆ˜áˆ™áˆ‹á‰µ (WebApp)", web_app=WebAppInfo(url=web_app_url))],
       [InlineKeyboardButton("ðŸš— áˆ˜áŠªáŠ“", callback_data="flow_buy_cat_car")],
       [InlineKeyboardButton("ðŸ  á‰¤á‰µ / á‰¦á‰³", callback_data="flow_buy_cat_house")],
       [InlineKeyboardButton("ðŸ¢ á‹¨áˆ¥áˆ« á‰¦á‰³ / áŠ•áŒá‹µ", callback_data="flow_buy_cat_commercial")],
       [InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")]
   ]
   await update.message.reply_text(
       "ðŸ” **á‹¨áˆšáˆáˆáŒ‰á‰µáŠ• áˆá‹µá‰¥ á‹­áˆáˆ¨áŒ¡á¦**\n\n"
       "ðŸ’¡ *á‰ áŠ áŠ•á‹µ áŒˆáŒ½ áˆ‹á‹­ á‰ á‰€áˆ‹áˆ‰ áˆˆáˆ˜áˆ™áˆ‹á‰µ 'á‰ áŽáˆ­áˆ á‰ ááŒ¥áŠá‰µ áˆˆáˆ˜áˆ™áˆ‹á‰µ' á‹¨áˆšáˆˆá‹áŠ• áŠ á‹áˆ«áˆ­ áˆ˜áŒ á‰€áˆ á‹­á‰½áˆ‹áˆ‰á¢*",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return BUYER_MAIN

async def buyer_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)

   await query.answer()
   cat = query.data.replace("flow_buy_cat_", "")
   context.user_data['main_category'] = cat

   if cat == "car":
       keyboard = [[InlineKeyboardButton(sub, callback_data=f"flow_buy_sub_{sub}")] for sub in CAR_SUB_CATEGORIES]
       keyboard.append([InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")])
       await query.edit_message_text(
           "ðŸš— **á‹¨áˆ˜áŠªáŠ“ áŠ á‹­áŠá‰µ/áˆžá‹´áˆ á‹­áˆáˆ¨áŒ¡á¦**",
           reply_markup=InlineKeyboardMarkup(keyboard),
           parse_mode="Markdown"
       )
       return BUYER_SUB
   else:
       keyboard = [
           [InlineKeyboardButton("ðŸ›ï¸ áˆ˜áŒá‹›á‰µ", callback_data="flow_buy_action_buy")],
           [InlineKeyboardButton("ðŸ”‘ áˆ˜áŠ¨áˆ«á‹¨á‰µ", callback_data="flow_buy_action_rent")],
           [InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")]
       ]
       await query.edit_message_text(
           "â“ **á‹¨áˆšáˆáˆáŒ‰á‰µáŠ• á‹¨á‹µáˆ­áŒŠá‰µ áŠ á‹­áŠá‰µ á‹­áˆáˆ¨áŒ¡á¦**",
           reply_markup=InlineKeyboardMarkup(keyboard),
           parse_mode="Markdown"
       )
       return BUYER_ACTION

async def buyer_sub_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)

   await query.answer()
   sub = query.data.replace("flow_buy_sub_", "")
   context.user_data['sub_category'] = sub

   keyboard = [
       [InlineKeyboardButton("ðŸ›ï¸ áˆ˜áŒá‹›á‰µ", callback_data="flow_buy_action_buy")],
       [InlineKeyboardButton("ðŸ”‘ áˆ˜áŠ¨áˆ«á‹¨á‰µ", callback_data="flow_buy_action_rent")],
       [InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")]
   ]
   await query.edit_message_text(
       f"âœ… {sub}\n\nâ“ **á‹¨áˆšáˆáˆáŒ‰á‰µáŠ• á‹¨á‹µáˆ­áŒŠá‰µ áŠ á‹­áŠá‰µ á‹­áˆáˆ¨áŒ¡á¦**",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return BUYER_ACTION

async def buyer_action_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)

   await query.answer()
   action = query.data.replace("flow_buy_action_", "")
   context.user_data['action_type'] = "áˆ˜áŒá‹›á‰µ" if action == "buy" else "áˆ˜áŠ¨áˆ«á‹¨á‰µ"

   await query.edit_message_text(
       "ðŸ’° **á‹¨á‰ áŒ€á‰µ áŠ­áˆáˆá‹ŽáŠ• á‹«áˆµáŒˆá‰¡á¦**\n\n"
       "ðŸ’¡ *áˆáˆ³áˆŒá¦* `500000-1000000` (áŠ¨ 500áˆºáˆ… áŠ¥áˆµáŠ¨ 1 áˆšáˆŠá‹®áŠ• á‰¥áˆ­)\n"
       "á‹ˆá‹­áˆ áŠ áŠ•á‹µ á‰áŒ¥áˆ­ á‰¥á‰» á‹«áˆµáŒˆá‰¡ (áˆˆáˆáˆ³áˆŒ 2000000)",
       parse_mode="Markdown"
   )
   return BUYER_BUDGET_RANGE

async def buyer_budget_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
   if update.message.text == "ðŸ  á‹‹áŠ“ áŒˆáŒ½":
       return await go_home(update, context)
   
   context.user_data['budget_range'] = update.message.text.strip()
   
   keyboard = [
       [InlineKeyboardButton("âœ… áŠ á‹Ž - áˆ›áˆ³á‹ˆá‰‚á‹« á‹°áˆ­áˆ¶áŠ", callback_data="alert_yes")],
       [InlineKeyboardButton("âŒ áŠ á‹­ - áŠ á‹«áˆµáˆáˆáŒˆáŠáˆ", callback_data="alert_no")],
       [InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")]
   ]
   await update.message.reply_text(
       "ðŸ”” **á‰°áˆ˜áˆ³áˆ³á‹­ áŠ•á‰¥áˆ¨á‰µ áˆ²áˆˆá‰€á‰… áˆ›áˆ³á‹ˆá‰‚á‹« áŠ¥áŠ•á‹²á‹°áˆ­áˆµá‹Ž á‹­áˆáˆáŒ‹áˆ‰?**",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return BUYER_ALERT

async def buyer_alert_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)
   
   await query.answer()
   context.user_data['create_alert'] = (query.data == "alert_yes")
   
   if context.user_data.get('main_category') == "car":
       await query.edit_message_text(
           "âœï¸ **á‹¨áˆšáˆáˆáŒ‰á‰µáŠ• áˆ˜áŠªáŠ“ á‹áˆ­á‹áˆ­ áˆ˜áˆ¨áŒƒ á‹«áˆµáŒˆá‰¡á¦**\n\nðŸ’¡ *áˆáˆ³áˆŒá¦* á‰¶á‹®á‰³ á‰ªá‰µá‹ 2020á£ áŠáŒ­ á‰€áˆˆáˆá£ áŠ¦á‰¶áˆ›á‰²áŠ­",
           parse_mode="Markdown"
       )
       return BUYER_DETAILS
   else:
       keyboard = [[InlineKeyboardButton(ptype, callback_data=f"flow_buy_prop_{ptype}")] for ptype in PROPERTY_TYPES]
       keyboard.append([InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")])
       await query.edit_message_text(
           "ðŸ  **á‹¨áŠ•á‰¥áˆ¨á‰µ áŠ á‹­áŠá‰µ á‹­áˆáˆ¨áŒ¡á¦**",
           reply_markup=InlineKeyboardMarkup(keyboard),
           parse_mode="Markdown"
       )
       return BUYER_PROPERTY

async def buyer_property_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)

   await query.answer()
   prop = query.data.replace("flow_buy_prop_", "")
   context.user_data['property_type'] = prop

   keyboard = [[InlineKeyboardButton(htype, callback_data=f"flow_buy_htype_{htype}")] for htype in HOUSE_TYPES]
   keyboard.append([InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")])
   await query.edit_message_text(
       "ðŸ  **á‹¨á‰¤á‰± áŠ á‹­áŠá‰µ á‹­áˆáˆ¨áŒ¡á¦**",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return BUYER_HTYPE

async def buyer_htype_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)

   await query.answer()
   htype = query.data.replace("flow_buy_htype_", "")
   context.user_data['property_subtype'] = htype

   await query.edit_message_text(
       f"ðŸ  **á‹¨á‰¤á‰± áŠ á‹­áŠá‰µá¦ {htype}**\n\nâœï¸ **á‹¨áˆšáˆáˆáŒ‰á‰µáŠ• á‰¤á‰µ/á‰¦á‰³ á‹áˆ­á‹áˆ­ áˆ˜áˆ¨áŒƒ á‹«áˆµáŒˆá‰¡á¦**\n\nðŸ’¡ *áˆáˆ³áˆŒá¦* á‰¦áˆŒ 2 áˆ˜áŠá‰³á£ á“áˆ­áŠªáŠ•áŒ á‹«áˆˆá‹",
       parse_mode="Markdown"
   )
   return BUYER_DETAILS

async def buyer_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
   if update.message.text == "ðŸ  á‹‹áŠ“ áŒˆáŒ½":
       return await go_home(update, context)
   context.user_data['description'] = update.message.text
   await update.message.reply_text(
       "ðŸ“ž **áˆµáˆáŠ­ á‰áŒ¥áˆ­á‹ŽáŠ• á‹«áˆµáŒˆá‰¡á¦**\n\n"
       "ðŸ“± **Telegram Username (áŠ áˆ›áˆ«áŒ­)** áˆ›áŠ¨áˆ áŠ¨áˆáˆˆáŒ‰ áŠ¨áˆµáˆáŠ© áŒ‹áˆ­ á‹«áˆµáŒˆá‰¡á¢\n"
       "ðŸ’¡ *áˆˆáˆáˆ³áˆŒá¦* `0911223344 @Abebe`",
       parse_mode="Markdown",
       reply_markup=ReplyKeyboardMarkup([["ðŸ  á‹‹áŠ“ áŒˆáŒ½"]], resize_keyboard=True)
   )
   return BUYER_PHONE


async def buyer_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
   if update.message.text == "ðŸ  á‹‹áŠ“ áŒˆáŒ½":
       return await go_home(update, context)

   text = update.message.text.strip()
   
   # Telegram username áˆ›á‹áŒ£á‰µ (áŠ«áˆˆ)
   telegram_user = ""
   phone = text
   
   # @username áˆáˆáŒŽ áˆ›á‹áŒ£á‰µ
   import re
   username_match = re.search(r'@\w+', text)
   if username_match:
       telegram_user = username_match.group()
       phone = text.replace(telegram_user, '').strip()
   
   if not validate_phone(phone):
       await update.message.reply_text("âŒ á‰µáŠ­áŠ­áˆˆáŠ› á‹¨áˆµáˆáŠ­ á‰áŒ¥áˆ­ á‹«áˆµáŒˆá‰¡á¢ (áˆˆáˆáˆ³áˆŒá¦ 0911223344 á‹ˆá‹­áˆ 0911223344 @Abebe)")
       return BUYER_PHONE

   context.user_data["phone"] = phone
   context.user_data["telegram_user"] = telegram_user
   
   # á‰ á‰€áŒ¥á‰³ áˆ›áˆµá‰€áˆ˜áŒ¥
   user = update.effective_user
   user_data = context.user_data

   desc = user_data.get('description', '')
   budget = user_data.get('budget_range', '')
   main_category = user_data.get('main_category', '')
   
   if user_data.get('property_subtype'):
       desc = f"ðŸ  {user_data.get('property_subtype')}\n{desc}"

   try:
       req_id = add_listing(
           user_chat_id=user.id,
           user_name=user.first_name or "User",
           req_type="BUY",
           main_category=main_category,
           sub_category=user_data.get('sub_category', ''),
           action_type=user_data.get('action_type', 'áˆ˜áŒá‹›á‰µ'),
           property_type=user_data.get('property_type', ''),
           description=desc,
           price=budget,
           phone=phone,
           extra_data={
               'create_alert': user_data.get('create_alert', False),
               'budget_range': budget,
               'telegram_user': telegram_user
           }
       )

       if req_id:
           await update.message.reply_text(
               f"âœ… **áŒ¥á‹«á‰„á‹Ž á‰ áˆµáŠ¬á‰µ á‰°áˆ˜á‹áŒá‰§áˆ!** ðŸŽ‰\n\n"
               f"ðŸ†” **á‹¨áŒ¥á‹«á‰„ á‰áŒ¥áˆ­:** #ADK-{req_id}\n"
               f"ðŸ“Œ **áˆá‹µá‰¥:** {main_category}\n"
               f"ðŸ“ž **áˆµáˆáŠ­:** {phone}\n"
               + (f"ðŸ“± **Telegram:** {telegram_user}\n" if telegram_user else "") +
               f"\náŠ á‰…áˆ«á‰¢á‹Žá‰½ á‹ˆá‹­áˆ á‹°áˆ‹áˆŽá‰½ áŒ¥á‹«á‰„á‹ŽáŠ• áŠ á‹­á‰°á‹ áˆ˜áˆáˆµ á‹­áˆ°áŒ¡á‹Žá‰³áˆá¢",
               reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
               parse_mode="Markdown",
           )

           # áˆˆá‹°áˆ‹áˆŽá‰½ áˆ›áˆ³á‹ˆá‰‚á‹«
           notification_text = (
               f"ðŸ”” **áŠ á‹²áˆµ áŒ¥á‹«á‰„! (#ADK-{req_id})**\n\n"
               f"ðŸ“Œ **á‹˜áˆ­áá¦** {main_category}\n"
               f"ðŸ“ **ááˆ‹áŒŽá‰µá¦** {user_data.get('description', '')}\n"
               f"ðŸ’° **á‰ áŒ€á‰µá¦** {budget}\n"
               f"ðŸ“ž **áˆµáˆáŠ­á¦** {phone}\n"
               + (f"ðŸ“± **Telegram:** {telegram_user}\n" if telegram_user else "") +
               f"\nðŸ‘‰ á‹­áˆ… áŠ•á‰¥áˆ¨á‰µ á‰ áŠ¥áŒ…á‹Ž áŠ«áˆˆ **'ðŸ¤ áŒˆá‹¢/á‰°áŠ¨áˆ«á‹­ áŠ áˆˆáŠ'** á‹¨áˆšáˆˆá‹áŠ• á‹­áŒ«áŠ‘!"
           )
           await notify_brokers(context.bot, notification_text, req_id, user.id)
       else:
           await update.message.reply_text(
               "âŒ **áˆ˜áˆ¨áŒƒá‹áŠ• áˆ˜áˆ˜á‹áŒˆá‰¥ áŠ áˆá‰°á‰»áˆˆáˆá¢**",
               reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
               parse_mode="Markdown"
           )
   except Exception as e:
       logger.error(f"âŒ Buyer save error: {e}", exc_info=True)
       await update.message.reply_text(
           "âŒ **áˆµáˆ…á‰°á‰µ á‰°áŠ¨áˆµá‰·áˆá¢** áŠ¥á‰£áŠ­á‹Ž áŠ¥áŠ•á‹°áŒˆáŠ“ á‹­áˆžáŠ­áˆ©á¢",
           reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
           parse_mode="Markdown"
       )

   context.user_data.clear()
   return ConversationHandler.END
# ==============================================================================
# 10. SELLER FLOW
# ==============================================================================

async def seller_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
   context.user_data.clear()
   context.user_data['req_type'] = 'SELL'

   web_app_url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'adika-vrkk.onrender.com')}/seller-form"

   keyboard = [
       [InlineKeyboardButton("ðŸŒ á‰ áŽáˆ­áˆ á‰ ááŒ¥áŠá‰µ áˆˆáˆ˜áˆ™áˆ‹á‰µ (WebApp)", web_app=WebAppInfo(url=web_app_url))],
       [InlineKeyboardButton("ðŸš— áˆ˜áŠªáŠ“", callback_data="flow_sell_cat_car")],
       [InlineKeyboardButton("ðŸ  á‰¤á‰µ / á‰¦á‰³", callback_data="flow_sell_cat_house")],
       [InlineKeyboardButton("ðŸ¢ á‹¨áˆ¥áˆ« á‰¦á‰³ / áŠ•áŒá‹µ", callback_data="flow_sell_cat_commercial")],
       [InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")]
   ]
   await update.message.reply_text(
       "ðŸ“¢ **á‹¨áˆšáˆ¸áŒ¡á‰µáŠ• á‹ˆá‹­áˆ á‹¨áˆšá‹«áŠ¨áˆ«á‹©á‰µáŠ• áˆá‹µá‰¥ á‹­áˆáˆ¨áŒ¡á¦**\n\n"
       "ðŸ’¡ *á‰ áŠ áŠ•á‹µ áŒˆáŒ½ áˆ‹á‹­ á‰ á‰€áˆ‹áˆ‰ áˆˆáˆ˜áˆ™áˆ‹á‰µ 'á‰ áŽáˆ­áˆ á‰ ááŒ¥áŠá‰µ áˆˆáˆ˜áˆ™áˆ‹á‰µ' á‹¨áˆšáˆˆá‹áŠ• áŠ á‹áˆ«áˆ­ áˆ˜áŒ á‰€áˆ á‹­á‰½áˆ‹áˆ‰á¢*",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return SELLER_MAIN

async def seller_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)

   await query.answer()
   cat = query.data.replace("flow_sell_cat_", "")
   context.user_data['main_category'] = cat

   if cat == "car":
       keyboard = [[InlineKeyboardButton(sub, callback_data=f"flow_sell_sub_{sub}")] for sub in CAR_SUB_CATEGORIES]
       keyboard.append([InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")])
       await query.edit_message_text(
           "ðŸš— **á‹¨áˆ˜áŠªáŠ“ áŠ á‹­áŠá‰µ/áˆžá‹´áˆ á‹­áˆáˆ¨áŒ¡á¦**",
           reply_markup=InlineKeyboardMarkup(keyboard),
           parse_mode="Markdown"
       )
       return SELLER_SUB
   else:
       keyboard = [
           [InlineKeyboardButton("ðŸ›ï¸ áˆ˜áˆ¸áŒ¥", callback_data="flow_sell_action_sell")],
           [InlineKeyboardButton("ðŸ”‘ áˆ›áŠ¨áˆ«á‹¨á‰µ", callback_data="flow_sell_action_rent")],
           [InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")]
       ]
       await query.edit_message_text(
           "â“ **á‹¨á‹µáˆ­áŒŠá‰µ áŠ á‹­áŠá‰µ á‹­áˆáˆ¨áŒ¡á¦**",
           reply_markup=InlineKeyboardMarkup(keyboard),
           parse_mode="Markdown"
       )
       return SELLER_ACTION

async def seller_sub_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)

   await query.answer()
   sub = query.data.replace("flow_sell_sub_", "")
   context.user_data['sub_category'] = sub

   keyboard = [
       [InlineKeyboardButton("ðŸ›ï¸ áˆ˜áˆ¸áŒ¥", callback_data="flow_sell_action_sell")],
       [InlineKeyboardButton("ðŸ”‘ áˆ›áŠ¨áˆ«á‹¨á‰µ", callback_data="flow_sell_action_rent")],
       [InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")]
   ]
   await query.edit_message_text(
       f"âœ… {sub}\n\nâ“ **á‹¨á‹µáˆ­áŒŠá‰µ áŠ á‹­áŠá‰µ á‹­áˆáˆ¨áŒ¡á¦**",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return SELLER_ACTION

async def seller_action_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)

   await query.answer()
   action = query.data.replace("flow_sell_action_", "")
   context.user_data['action_type'] = "áˆ˜áˆ¸áŒ¥" if action == "sell" else "áˆ›áŠ¨áˆ«á‹¨á‰µ"

   if context.user_data.get('main_category') == "car":
       # á‹¨áˆ˜áŠªáŠ“ áˆáŠ”á‰³ áˆ˜áŒ á‹¨á‰…
       keyboard = [[InlineKeyboardButton(cond, callback_data=f"flow_sell_cond_{cond}")] for cond in CONDITIONS]
       keyboard.append([InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")])
       await query.edit_message_text(
           "ðŸ“Š **á‹¨áˆ˜áŠªáŠ“á‹áŠ• áˆáŠ”á‰³ á‹­áˆáˆ¨áŒ¡á¦**",
           reply_markup=InlineKeyboardMarkup(keyboard),
           parse_mode="Markdown"
       )
       return SELLER_CONDITION
   else:
       keyboard = [[InlineKeyboardButton(ptype, callback_data=f"flow_sell_prop_{ptype}")] for ptype in PROPERTY_TYPES]
       keyboard.append([InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")])
       await query.edit_message_text(
           "ðŸ  **á‹¨áŠ•á‰¥áˆ¨á‰µ áŠ á‹­áŠá‰µ á‹­áˆáˆ¨áŒ¡á¦**",
           reply_markup=InlineKeyboardMarkup(keyboard),
           parse_mode="Markdown"
       )
       return SELLER_PROPERTY

async def seller_condition_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)

   await query.answer()
   cond = query.data.replace("flow_sell_cond_", "")
   context.user_data['condition'] = cond
   
   # á‹¨áŠá‹³áŒ… áŠ á‹­áŠá‰µ
   keyboard = [[InlineKeyboardButton(ftype, callback_data=f"flow_sell_fuel_{ftype}")] for ftype in FUEL_TYPES]
   keyboard.append([InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")])
   await query.edit_message_text(
       f"âœ… **áˆáŠ”á‰³:** {cond}\n\nâ›½ **á‹¨áŠá‹³áŒ… áŠ á‹­áŠá‰µ á‹­áˆáˆ¨áŒ¡á¦**",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return SELLER_FUEL

async def seller_fuel_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)

   await query.answer()
   fuel = query.data.replace("flow_sell_fuel_", "")
   context.user_data['fuel_type'] = fuel
   
   # áˆ›áˆ­áˆ½
   keyboard = [[InlineKeyboardButton(ttype, callback_data=f"flow_sell_trans_{ttype}")] for ttype in TRANSMISSION_TYPES]
   keyboard.append([InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")])
   await query.edit_message_text(
       f"â›½ **áŠá‹³áŒ…:** {fuel}\n\nâš™ï¸ **á‹¨áˆ›áˆ­áˆ½ áŠ á‹­áŠá‰µ á‹­áˆáˆ¨áŒ¡á¦**",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return SELLER_TRANSMISSION

async def seller_transmission_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)

   await query.answer()
   trans = query.data.replace("flow_sell_trans_", "")
   context.user_data['transmission'] = trans
   
   await query.edit_message_text(
       f"âš™ï¸ **áˆ›áˆ­áˆ½:** {trans}\n\nðŸ›£ï¸ **á‹¨áŠªáˆŽáˆœá‰µáˆ­ áˆ˜áŒ áŠ• á‹«áˆµáŒˆá‰¡ (KM)á¦**\n\nðŸ’¡ *áˆˆáˆáˆ³áˆŒá¦* 50000",
       parse_mode="Markdown"
   )
   return SELLER_MILEAGE

async def seller_mileage(update: Update, context: ContextTypes.DEFAULT_TYPE):
   if update.message.text == "ðŸ  á‹‹áŠ“ áŒˆáŒ½":
       return await go_home(update, context)
   
   if not update.message.text.isdigit():
       await update.message.reply_text("âŒ áŠ¥á‰£áŠ­á‹Ž á‰áŒ¥áˆ­ á‰¥á‰» á‹«áˆµáŒˆá‰¡á¢")
       return SELLER_MILEAGE
   
   context.user_data['mileage'] = update.message.text
   
   await update.message.reply_text(
       "âœï¸ **á‹¨áˆ˜áŠªáŠ“á‹áŠ• á‹áˆ­á‹áˆ­ áˆ˜áˆ¨áŒƒ á‹«áˆµáŒˆá‰¡á¦**\n\nðŸ’¡ *áˆáˆ³áˆŒá¦* á‰¶á‹®á‰³ á‰ªá‰µá‹ 2020á£ áŠáŒ­á£ áŠ á‹²áˆµ áŒŽáˆ›á£ áŠ áŠ­áˆ²á‹°áŠ•á‰µ á‹«áˆáŒˆáŒ áˆ˜á‹",
       parse_mode="Markdown"
   )
   return SELLER_DETAILS

async def seller_property_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)

   await query.answer()
   prop = query.data.replace("flow_sell_prop_", "")
   context.user_data['property_type'] = prop

   keyboard = [[InlineKeyboardButton(htype, callback_data=f"flow_sell_htype_{htype}")] for htype in HOUSE_TYPES]
   keyboard.append([InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")])

   await query.edit_message_text(
       "ðŸ  **á‹¨á‰¤á‰± áŠ á‹­áŠá‰µ á‹­áˆáˆ¨áŒ¡á¦**",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return SELLER_HTYPE

async def seller_htype_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)

   await query.answer()
   htype = query.data.replace("flow_sell_htype_", "")
   context.user_data['property_subtype'] = htype
   
   # á‹¨á‰¤á‰µ áˆáŠ”á‰³
   conditions = ["ðŸ†• áŠ á‹²áˆµ", "âœ… áŒ¥áˆ©", "ðŸ”§ áŠ¥á‹µáˆ³á‰µ á‹¨áˆšáˆáˆáŒ"]
   keyboard = [[InlineKeyboardButton(cond, callback_data=f"flow_sell_cond_{cond}")] for cond in conditions]
   keyboard.append([InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")])
   await query.edit_message_text(
       f"ðŸ  **á‹¨á‰¤á‰± áŠ á‹­áŠá‰µá¦** {htype}\n\nðŸ“Š **á‹¨á‰¤á‰±áŠ• áˆáŠ”á‰³ á‹­áˆáˆ¨áŒ¡á¦**",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return SELLER_CONDITION

async def seller_house_condition_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)

   await query.answer()
   cond = query.data.replace("flow_sell_cond_", "")
   context.user_data['condition'] = cond
   
   # á‹¨áˆ˜áŠá‰³ á‰¥á‹›á‰µ
   keyboard = [
       [InlineKeyboardButton("1", callback_data="bed_1"), InlineKeyboardButton("2", callback_data="bed_2")],
       [InlineKeyboardButton("3", callback_data="bed_3"), InlineKeyboardButton("4", callback_data="bed_4")],
       [InlineKeyboardButton("5+", callback_data="bed_5+")],
       [InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")]
   ]
   await query.edit_message_text(
       f"ðŸ“Š **áˆáŠ”á‰³:** {cond}\n\nðŸ›ï¸ **á‹¨áˆ˜áŠá‰³ áŠ­ááˆ á‰¥á‹›á‰µ á‹­áˆáˆ¨áŒ¡á¦**",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return SELLER_BEDROOMS

async def seller_bedrooms_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)

   await query.answer()
   beds = query.data.replace("bed_", "")
   context.user_data['bedrooms'] = beds
   
   # á“áˆ­áŠªáŠ•áŒ
   keyboard = [
       [InlineKeyboardButton("ðŸš— áŠ áˆˆ", callback_data="park_yes")],
       [InlineKeyboardButton("âŒ á‹¨áˆˆáˆ", callback_data="park_no")],
       [InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")]
   ]
   await query.edit_message_text(
       f"ðŸ›ï¸ **áˆ˜áŠá‰³:** {beds}\n\nðŸš— **á“áˆ­áŠªáŠ•áŒ áŠ áˆˆá‹?**",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return SELLER_PARKING

async def seller_parking_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)

   await query.answer()
   parking = "áŠ áˆˆ" if query.data == "park_yes" else "á‹¨áˆˆáˆ"
   context.user_data['parking'] = parking
   
   await query.edit_message_text(
       f"ðŸš— **á“áˆ­áŠªáŠ•áŒ:** {parking}\n\nâœï¸ **á‹¨á‰¤á‰±áŠ•/á‰¦á‰³á‹áŠ• á‹áˆ­á‹áˆ­ áˆ˜áˆ¨áŒƒ á‹«áˆµáŒˆá‰¡á¦**\nðŸ’¡ *áˆáˆ³áˆŒá¦* á‰¦áˆŒ áŠ á‰µáˆ‹áˆµ áŠ áŠ«á‰£á‰¢ 3 áˆ˜áŠá‰³ á‰¤á‰µá£ á‹˜áˆ˜áŠ“á‹Š áŠ©áˆ½áŠ“",
       parse_mode="Markdown"
   )
   return SELLER_DETAILS

async def seller_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
   if update.message.text == "ðŸ  á‹‹áŠ“ áŒˆáŒ½":
       return await go_home(update, context)
   context.user_data['description'] = update.message.text
   await update.message.reply_text(
       "ðŸ’° **á‹¨áˆšáˆ¸áŒ¡á‰ á‰µáŠ•/áˆšá‹«áŠ¨áˆ«á‹©á‰ á‰µáŠ• á‹‹áŒ‹ á‹«áˆµáŒˆá‰¡á¦**",
       reply_markup=ReplyKeyboardMarkup([["ðŸ  á‹‹áŠ“ áŒˆáŒ½"]], resize_keyboard=True),
       parse_mode="Markdown"
   )
   return SELLER_PRICE

async def seller_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
   if update.message.text == "ðŸ  á‹‹áŠ“ áŒˆáŒ½":
       return await go_home(update, context)

   if not validate_price(update.message.text):
       await update.message.reply_text("âŒ áŠ¥á‰£áŠ­á‹Ž á‰áŒ¥áˆ­ á‰¥á‰» á‹«áˆµáŒˆá‰¡á¢")
       return SELLER_PRICE

   context.user_data['price'] = update.message.text
   
   # á‹¨áˆšá‹°áˆ«á‹°áˆ­ áŠá‹?
   keyboard = [
       [InlineKeyboardButton("âœ… áŠ á‹Ž - á‹¨áˆšá‹°áˆ«á‹°áˆ­", callback_data="negotiable_yes")],
       [InlineKeyboardButton("âŒ áŠ á‹­ - á‹¨áˆ›á‹­á‹°áˆ«á‹°áˆ­", callback_data="negotiable_no")],
       [InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")]
   ]
   await update.message.reply_text(
       "ðŸ’° **á‹‹áŒ‹á‹ á‹¨áˆšá‹°áˆ«á‹°áˆ­ áŠá‹?**",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return SELLER_NEGOTIABLE

async def seller_negotiable_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)

   await query.answer()
   context.user_data['negotiable'] = (query.data == "negotiable_yes")
   
   # áŠ áˆµá‰¸áŠ³á‹­ áˆ½á‹«áŒ­?
   keyboard = [
       [InlineKeyboardButton("âš¡ áŠ á‹Ž - áŠ áˆµá‰¸áŠ³á‹­ áŠá‹", callback_data="urgent_yes")],
       [InlineKeyboardButton("âŒ áŠ á‹­ - áŠ áˆµá‰¸áŠ³á‹­ áŠ á‹­á‹°áˆˆáˆ", callback_data="urgent_no")],
       [InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")]
   ]
   await query.edit_message_text(
       "âš¡ **á‹­áˆ… áŠ áˆµá‰¸áŠ³á‹­ áˆ½á‹«áŒ­ áŠá‹?**",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return SELLER_URGENT

async def seller_urgent_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)

   await query.answer()
   context.user_data['urgent_sale'] = (query.data == "urgent_yes")
   
   await query.edit_message_text(
       "ðŸ“ž **á‹¨áˆµáˆáŠ­ á‰áŒ¥áˆ­á‹ŽáŠ• á‹«áˆµáŒˆá‰¡á¦**",
       parse_mode="Markdown"
   )
   return SELLER_PHONE

async def seller_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
   if update.message.text == "ðŸ  á‹‹áŠ“ áŒˆáŒ½":
       return await go_home(update, context)

   if not validate_phone(update.message.text):
       await update.message.reply_text("âŒ á‰µáŠ­áŠ­áˆˆáŠ› á‹¨áˆµáˆáŠ­ á‰áŒ¥áˆ­ á‹«áˆµáŒˆá‰¡á¢")
       return SELLER_PHONE

   context.user_data['phone'] = update.message.text
   await update.message.reply_text(
       "ðŸ“¸ **á‹¨áŠ•á‰¥áˆ¨á‰±áŠ• áŽá‰¶ á‹­áˆ‹áŠ© (á‹ˆá‹­áˆ 'á‹áˆˆáˆ' á‹¨áˆšáˆˆá‹áŠ• á‹­áŒ»á‰)á¦**\n\n"
       "ðŸ’¡ *áŠ¥áˆµáŠ¨ 5 áŽá‰¶á‹Žá‰½ áˆ˜áˆ‹áŠ­ á‹­á‰½áˆ‹áˆ‰á¢ áˆ²áŒ¨áˆ­áˆ± 'áŒ¨áˆ¨áˆµáŠ©' á‰¥áˆˆá‹ á‹­áŒ»á‰á¢*",
       parse_mode="Markdown"
   )
   return SELLER_PHOTO

async def seller_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
   if update.message.text == "ðŸ  á‹‹áŠ“ áŒˆáŒ½":
       return await go_home(update, context)

   if not validate_phone(update.message.text):
       await update.message.reply_text("âŒ á‰µáŠ­áŠ­áˆˆáŠ› á‹¨áˆµáˆáŠ­ á‰áŒ¥áˆ­ á‹«áˆµáŒˆá‰¡á¢")
       return SELLER_PHONE

   context.user_data['phone'] = update.message.text
   
   # Telegram username áˆ˜áŒ á‹¨á‰…
   await update.message.reply_text(
       "ðŸ“± **Telegram Username á‹«áˆµáŒˆá‰¡ (áŠ áˆ›áˆ«áŒ­)á¦**\n\n"
       "ðŸ’¡ *áˆˆáˆáˆ³áˆŒá¦* @Abebe_Belay\n"
       "á‹ˆá‹­áˆ 'á‹áˆˆáˆ' á‰¥áˆˆá‹ á‹­áŒ»á‰á¢",
       parse_mode="Markdown",
       reply_markup=ReplyKeyboardMarkup([["á‹áˆˆáˆ"], ["ðŸ  á‹‹áŠ“ áŒˆáŒ½"]], resize_keyboard=True)
   )
   return SELLER_PHOTO  # á‹ˆá‹° áŽá‰¶ áŠ¨áˆ˜áˆ„á‹µ á‰ áŠá‰µ username áŠ¥áŠ•á‰€á‰ áˆ‹áˆˆáŠ•


async def seller_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
   if update.message.text == "ðŸ  á‹‹áŠ“ áŒˆáŒ½":
       return await go_home(update, context)

   text = update.message.text.strip()
   
   # Telegram username áˆ›á‹áŒ£á‰µ (áŠ«áˆˆ)
   import re
   telegram_user = ""
   phone = text
   
   username_match = re.search(r'@\w+', text)
   if username_match:
       telegram_user = username_match.group()
       phone = text.replace(telegram_user, '').strip()
   
   if not validate_phone(phone):
       await update.message.reply_text("âŒ á‰µáŠ­áŠ­áˆˆáŠ› á‹¨áˆµáˆáŠ­ á‰áŒ¥áˆ­ á‹«áˆµáŒˆá‰¡á¢ (áˆˆáˆáˆ³áˆŒá¦ 0911223344 á‹ˆá‹­áˆ 0911223344 @Abebe)")
       return SELLER_PHONE

   context.user_data['phone'] = phone
   context.user_data['telegram_user'] = telegram_user
   
   # á‰ á‰€áŒ¥á‰³ á‹ˆá‹° áŽá‰¶ áˆ‚á‹µ
   await update.message.reply_text(
       "ðŸ“¸ **á‹¨áŠ•á‰¥áˆ¨á‰±áŠ• áŽá‰¶ á‹­áˆ‹áŠ© (á‹ˆá‹­áˆ 'á‹áˆˆáˆ' á‹¨áˆšáˆˆá‹áŠ• á‹­áŒ»á‰)á¦**\n\n"
       "ðŸ’¡ *áŠ¥áˆµáŠ¨ 5 áŽá‰¶á‹Žá‰½ áˆ˜áˆ‹áŠ­ á‹­á‰½áˆ‹áˆ‰á¢ áˆ²áŒ¨áˆ­áˆ± 'áŒ¨áˆ¨áˆµáŠ©' á‰¥áˆˆá‹ á‹­áŒ»á‰á¢*",
       parse_mode="Markdown",
       reply_markup=ReplyKeyboardMarkup([["á‹áˆˆáˆ"], ["áŒ¨áˆ¨áˆµáŠ©"], ["ðŸ  á‹‹áŠ“ áŒˆáŒ½"]], resize_keyboard=True)
   )
   return SELLER_PHOTO


async def seller_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
   user = update.effective_user
   
   if update.message.text == "ðŸ  á‹‹áŠ“ áŒˆáŒ½":
       return await go_home(update, context)
   
   # áŽá‰¶ áˆ›áˆµá‰°áŠ“áŒˆá‹µ
   if update.message.text and update.message.text.lower() in ['á‹áˆˆáˆ', 'áŒ¨áˆ¨áˆµáŠ©', 'á‰€áŒ¥áˆ']:
       return await save_seller_listing(update, context)
   
   if update.message.photo:
       if 'photos' not in context.user_data:
           context.user_data['photos'] = []
       
       if len(context.user_data['photos']) < 5:
           context.user_data['photos'].append(update.message.photo[-1].file_id)
           count = len(context.user_data['photos'])
           await update.message.reply_text(
               f"ðŸ“¸ **áŽá‰¶ {count}/5 á‰°á‰€á‰¥á‹«áˆˆáˆ!**\n\n"
               f"á‰°áŒ¨áˆ›áˆª áŽá‰¶ á‹­áˆ‹áŠ© á‹ˆá‹­áˆ áˆˆáˆ›á‰†áˆ 'áŒ¨áˆ¨áˆµáŠ©' á‰¥áˆˆá‹ á‹­áŒ»á‰á¢",
               parse_mode="Markdown"
           )
       else:
           await update.message.reply_text(
               "âš ï¸ áŠ¨áá‰°áŠ›á‹ 5 áŽá‰¶ áŠá‹á¢ 'áŒ¨áˆ¨áˆµáŠ©' á‰¥áˆˆá‹ á‹­áŒ»á‰á¢",
               parse_mode="Markdown"
           )
       return SELLER_PHOTO
   
   return SELLER_PHOTO

async def save_seller_listing(update: Update, context: ContextTypes.DEFAULT_TYPE):
   user = update.effective_user
   user_data = context.user_data

   property_subtype = user_data.get('property_subtype', '')
   description = user_data.get('description', '')
   telegram_user = user_data.get('telegram_user', '')
   
   # áˆ›áŒ á‰ƒáˆˆá‹« áŒ½áˆá áˆ˜áŒˆáŠ•á‰£á‰µ
   is_car = user_data.get('main_category') == "car"
   negotiable = user_data.get('negotiable', True)
   urgent_sale = user_data.get('urgent_sale', False)
   
   negotiable_text = "âœ… á‹¨áˆšá‹°áˆ«á‹°áˆ­" if negotiable else "âŒ á‹¨áˆ›á‹­á‹°áˆ«á‹°áˆ­"
   urgent_text = "âš¡ **áŠ áˆµá‰¸áŠ³á‹­ áˆ½á‹«áŒ­!** " if urgent_sale else ""
   
   if property_subtype:
       description = f"ðŸ  {property_subtype}\n{description}"

   desc = (
       f"{urgent_text}ðŸ“¢ **áŠ á‹²áˆµ á‹¨áˆ½á‹«áŒ­/áŠªáˆ«á‹­ áˆ›áˆµá‰³á‹ˆá‰‚á‹«!**\n"
       f"ðŸ”„ áŠ á‹­áŠá‰µ: {user_data.get('action_type')}\n"
       f"ðŸ“¦ áˆá‹µá‰¥: {user_data.get('main_category')}\n"
       f"ðŸ“ á‹áˆ­á‹áˆ­: {description}\n"
       f"ðŸ’° á‹‹áŒ‹: {user_data.get('price')} á‰¥áˆ­ ({negotiable_text})\n"
   )
   
   if is_car:
       if user_data.get('condition'): desc += f"ðŸ“Š áˆáŠ”á‰³: {user_data.get('condition')}\n"
       if user_data.get('fuel_type'): desc += f"â›½ áŠá‹³áŒ…: {user_data.get('fuel_type')}\n"
       if user_data.get('transmission'): desc += f"âš™ï¸ áˆ›áˆ­áˆ½: {user_data.get('transmission')}\n"
       if user_data.get('mileage'): desc += f"ðŸ›£ï¸ áŠªáˆŽáˆœá‰µáˆ­: {user_data.get('mileage')} KM\n"
   else:
       if user_data.get('condition'): desc += f"ðŸ“Š áˆáŠ”á‰³: {user_data.get('condition')}\n"
       if user_data.get('bedrooms'): desc += f"ðŸ›ï¸ áˆ˜áŠá‰³: {user_data.get('bedrooms')}\n"
       if user_data.get('parking'): desc += f"ðŸš— á“áˆ­áŠªáŠ•áŒ: {user_data.get('parking')}\n"
   
   desc += f"ðŸ“ž áˆµáˆáŠ­: {user_data.get('phone')}\n"
   if telegram_user: desc += f"ðŸ“± Telegram: {telegram_user}\n"
   
   # Extra data
   extra_data = {
       'negotiable': negotiable,
       'urgent_sale': urgent_sale,
       'telegram_user': telegram_user,
   }
   if is_car:
       extra_data.update({
           'condition': user_data.get('condition', ''),
           'fuel_type': user_data.get('fuel_type', ''),
           'transmission': user_data.get('transmission', ''),
           'mileage': user_data.get('mileage', ''),
           'car_type': user_data.get('sub_category', ''),
       })
   else:
       extra_data.update({
           'condition': user_data.get('condition', ''),
           'bedrooms': user_data.get('bedrooms', ''),
           'parking': user_data.get('parking', ''),
           'house_type': property_subtype,
       })

   photos = user_data.get('photos', [])
   photo_id = photos[0] if photos else None

   try:
       req_id = add_listing(
           user_chat_id=user.id,
           user_name=user.first_name or "User",
           req_type="SELL",
           main_category=user_data.get('main_category', ''),
           sub_category=user_data.get('sub_category', ''),
           action_type=user_data.get('action_type', 'áˆ˜áˆ¸áŒ¥'),
           property_type=user_data.get('property_type', ''),
           description=desc,
           price=user_data.get('price'),
           phone=user_data.get('phone'),
           photo_id=photo_id,
           extra_data=extra_data,
           photos=photos
       )

       if req_id:
           await update.message.reply_text(
               f"âœ… **áˆ›áˆµá‰³á‹ˆá‰‚á‹«á‹Ž á‰ áˆµáŠ¬á‰µ á‰°áˆ˜á‹áŒá‰§áˆ!** ðŸŽ‰\n\n"
               f"ðŸ†” **á‹¨áˆ›áˆµá‰³á‹ˆá‰‚á‹« á‰áŒ¥áˆ­:** #ADK-{req_id}\n"
               f"ðŸ“ž **áˆµáˆáŠ­:** {user_data.get('phone')}\n"
               + (f"ðŸ“± **Telegram:** {telegram_user}\n" if telegram_user else "") +
               f"\nðŸ“Œ áˆ›áˆµá‰³á‹ˆá‰‚á‹«á‹Ž áˆˆá‹°áˆ‹áˆŽá‰½ áŠ¥áŠ“ áˆˆáˆáˆ‹áŒŠá‹Žá‰½ á‰°áˆáŠ³áˆá¢",
               reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
               parse_mode="Markdown"
           )

           # Send first photo as separate message if exists
           if photos:
               try:
                   await update.message.reply_photo(
                       photo=photos[0],
                       caption=f"ðŸ“¸ **á‹¨áˆ›áˆµá‰³á‹ˆá‰‚á‹« #ADK-{req_id} áŽá‰¶**",
                       parse_mode="Markdown"
                   )
               except Exception as e:
                   logger.error(f"Failed to send photo: {e}")

           notification_text = (
               f"ðŸ“¢ **áŠ á‹²áˆµ á‹¨áˆ½á‹«áŒ­/áŠªáˆ«á‹­ áˆ›áˆµá‰³á‹ˆá‰‚á‹«! (#ADK-{req_id})**\n\n"
               f"{desc}\n\n"
               f"ðŸ‘‰ á‹­áˆ…áŠ• áˆ›áˆµá‰³á‹ˆá‰‚á‹« áˆˆáˆáˆ‹áŒŠá‹Žá‰½ áˆ›áˆ³á‹ˆá‰… á‹­á‰½áˆ‹áˆ‰!"
           )
           try:
               await notify_brokers(context.bot, notification_text, req_id, user.id)
           except Exception as e:
               logger.error(f"Failed to notify brokers: {e}")
       else:
           await update.message.reply_text(
               "âŒ **áˆ›áˆµá‰³á‹ˆá‰‚á‹«á‹áŠ• áˆ˜áˆ˜á‹áŒˆá‰¥ áŠ áˆá‰°á‰»áˆˆáˆá¢**\n\n"
               "áŠ¥á‰£áŠ­á‹Ž áŠ¥áŠ•á‹°áŒˆáŠ“ á‹­áˆžáŠ­áˆ© á‹ˆá‹­áˆ á‹¨á‹µáŒ‹á á‰¡á‹µáŠ“á‰½áŠ•áŠ• á‹«áŠáŒ‹áŒáˆ©á¢",
               reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
               parse_mode="Markdown"
           )
   except Exception as e:
       logger.error(f"âŒ Seller save error: {e}", exc_info=True)
       await update.message.reply_text(
           f"âŒ **áˆµáˆ…á‰°á‰µ á‰°áŠ¨áˆµá‰·áˆá¦** {str(e)[:100]}\n\n"
           "áŠ¥á‰£áŠ­á‹Ž áŠ¥áŠ•á‹°áŒˆáŠ“ á‹­áˆžáŠ­áˆ©á¢",
           reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
           parse_mode="Markdown"
       )

   context.user_data.clear()
   return ConversationHandler.END
# ==============================================================================
# 11. BROKER REGISTRATION
# ==============================================================================

async def broker_reg_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    keyboard = [
        [InlineKeyboardButton("ðŸ‘¨ðŸ’¼ á‹°áˆ‹áˆ‹", callback_data="role_broker")],
        [InlineKeyboardButton("ðŸš¢ áŠ áˆµáˆ˜áŒª / áŠ á‰…áˆ«á‰¢", callback_data="role_importer")],
        [InlineKeyboardButton("ðŸ‘¤ á‰£áˆˆá‰¤á‰µ / áŠ á‰…áˆ«á‰¢", callback_data="role_owner")],
        [InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")]
    ]
    await update.message.reply_text(
        "ðŸ“ **á‹¨áˆá‹áŒˆá‰£ áŠ á‹­áŠá‰µ á‹­áˆáˆ¨áŒ¡á¦**\n\n"
        "ðŸ’¡ *áˆ›á‰¥áˆ«áˆªá‹«á¦*\n"
        "â€¢ á‹°áˆ‹áˆ‹ - áˆ½á‹«áŒ­/áŠªáˆ«á‹­ á‹¨áˆšá‹«áˆ˜á‰»á‰½\n"
        "â€¢ áŠ áˆµáˆ˜áŒª/áŠ á‰…áˆ«á‰¢ - áŠ¨á‹áŒ­ á‹¨áˆšá‹«áˆµáŒˆá‰£\n"
        "â€¢ á‰£áˆˆá‰¤á‰µ/áŠ á‰…áˆ«á‰¢ - áŠ•á‰¥áˆ¨á‰µ á‹«áˆˆá‹",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return BROKER_ROLE

async def broker_role_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)

    await query.answer()
    role_map = {
        "role_broker": "á‹°áˆ‹áˆ‹",
        "role_importer": "áŠ áˆµáˆ˜áŒª/áŠ á‰…áˆ«á‰¢",
        "role_owner": "á‰£áˆˆá‰¤á‰µ/áŠ á‰…áˆ«á‰¢"
    }
    role = role_map.get(query.data, "áŠ á‰…áˆ«á‰¢")
    context.user_data['broker_role'] = role

    await query.edit_message_text(
        f"ðŸ‘¤ **áˆá‹áŒˆá‰£á¦ {role}**\n\n1ï¸âƒ£ áˆ™áˆ‰ áˆµáˆá‹ŽáŠ• á‹«áˆµáŒˆá‰¡á¦",
        parse_mode="Markdown"
    )
    return BROKER_NAME

async def broker_reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "ðŸ  á‹‹áŠ“ áŒˆáŒ½":
        return await go_home(update, context)

    context.user_data['broker_name'] = update.message.text
    await update.message.reply_text("2ï¸âƒ£ **á‹¨áˆµáˆáŠ­ á‰áŒ¥áˆ­á‹ŽáŠ• á‹«áˆµáŒˆá‰¡á¦**", parse_mode="Markdown")
    return BROKER_PHONE

async def broker_reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "ðŸ  á‹‹áŠ“ áŒˆáŒ½":
        return await go_home(update, context)

    if not validate_phone(update.message.text):
        await update.message.reply_text("âŒ á‰µáŠ­áŠ­áˆˆáŠ› á‹¨áˆµáˆáŠ­ á‰áŒ¥áˆ­ á‹«áˆµáŒˆá‰¡á¢ (áˆˆáˆáˆ³áˆŒá¦ 0911223344)")
        return BROKER_PHONE

    context.user_data['broker_phone'] = update.message.text

    keyboard = [[InlineKeyboardButton(sc, callback_data=f"broker_sc_{sc}")] for sc in SUB_CITIES]
    keyboard.append([InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")])
    await update.message.reply_text(
        "3ï¸âƒ£ **á‹¨áˆšáˆ°áˆ©á‰ á‰µáŠ• áŠ­ááˆˆ áŠ¨á‰°áˆ› á‹­áˆáˆ¨áŒ¡á¦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return BROKER_SUBCITY

async def broker_reg_subcity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)

    await query.answer()
    sub_city = query.data.replace("broker_sc_", "")
    context.user_data['broker_subcity'] = sub_city

    await query.edit_message_text(
        "4ï¸âƒ£ **á‹¨á‹á‹­á‹³ (National ID) á‹ˆá‹­áˆ á‹¨áŠá‹‹áˆªáŠá‰µ áˆ˜á‰³á‹ˆá‰‚á‹« áŽá‰¶ á‹«áŠ•áˆ±áŠ“ á‹­áˆ‹áŠ©á¦**\n\n"
        "ðŸ’¡ *á‹­áˆ… áˆˆáˆ›áˆ¨áŒ‹áŒˆáŒ« á‰¥á‰» áŠá‹*",
        parse_mode="Markdown"
    )
    return BROKER_NID_PHOTO

async def broker_reg_nid_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text == "ðŸ  á‹‹áŠ“ áŒˆáŒ½":
        return await go_home(update, context)

    user = update.effective_user
    photo_id = update.message.photo[-1].file_id if update.message.photo else None

    if not photo_id:
        await update.message.reply_text("âŒ áŠ¥á‰£áŠ­á‹Ž á‹¨áˆ˜á‰³á‹ˆá‰‚á‹« áŽá‰¶ á‹­áˆ‹áŠ©á¢")
        return BROKER_NID_PHOTO

    role = context.user_data.get('broker_role', 'áŠ á‰…áˆ«á‰¢')
    name = context.user_data.get('broker_name', user.first_name)
    phone = context.user_data.get('broker_phone', '')
    sub_city = context.user_data.get('broker_subcity', '')

    broker_id = add_broker(user.id, name, phone, role, photo_id, sub_city)

    if broker_id:
        await update.message.reply_text(
            "âœ… **áˆá‹áŒˆá‰£á‹Ž á‰ áˆµáŠ¬á‰µ á‰°áŒ áŠ“á‰‹áˆ!** ðŸŽ‰\n\n"
            "â³ áŠ á‹µáˆšáŠ‘ áˆ˜áˆ¨áŒƒá‹ŽáŠ• áŠ«áˆ¨áŒ‹áŒˆáŒ  á‰ áŠ‹áˆ‹ áˆ›áˆµá‰³á‹ˆá‰‚á‹« á‹­á‹°áˆ­áˆµá‹Žá‰³áˆá¢",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )

        if ADMIN_CHAT_ID_INT != 0:
            admin_msg = (
                f"ðŸš¨ **áŠ á‹²áˆµ á‹¨{role} áˆá‹áŒˆá‰£ áŒ¥á‹«á‰„!**\n\n"
                f"ðŸ‘¤ áˆµáˆ: {name}\n"
                f"ðŸŽ­ áˆšáŠ“: {role}\n"
                f"ðŸ“ž áˆµáˆáŠ­: {phone}\n"
                f"ðŸ“ áŠ­ááˆˆ áŠ¨á‰°áˆ›: {sub_city}\n"
                f"ðŸ†” Telegram ID: `{user.id}`"
            )
            admin_kbd = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("âœ… áŠ áŒ½á‹µá‰…", callback_data=f"admin_appr_{user.id}"),
                    InlineKeyboardButton("âŒ áˆ°áˆ­á‹", callback_data=f"admin_reje_{user.id}")
                ]
            ])
            try:
                await context.bot.send_photo(
                    chat_id=ADMIN_CHAT_ID_INT,
                    photo=photo_id,
                    caption=admin_msg,
                    parse_mode="Markdown",
                    reply_markup=admin_kbd
                )
            except Exception as e:
                logger.error(f"Failed to send admin approval message: {e}")
    else:
        await update.message.reply_text(
            "âŒ **áˆá‹áŒˆá‰£á‹áŠ• áˆ›áŒ áŠ“á‰€á‰… áŠ áˆá‰°á‰»áˆˆáˆ!** áŠ¥á‰£áŠ­á‹Ž áŠ¥áŠ•á‹°áŒˆáŠ“ á‹­áˆžáŠ­áˆ©á¢",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )

    context.user_data.clear()
    return ConversationHandler.END

# ==============================================================================
# 12. BROKER OFFER FLOW
# ==============================================================================

async def broker_have_item_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """á‹°áˆ‹áˆ‹ 'áŠ áˆˆáŠ' áˆ²áŒ«áŠ• - áˆˆáˆáˆ‹áŒŠ áŒ¥á‹«á‰„"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    broker = get_broker(user_id)

    if not broker or broker.get('status') != 'approved':
        await query.message.reply_text(
            "â›” **á‹­áˆ…áŠ• áˆ›á‹µáˆ¨áŒ á‹¨áˆšá‰½áˆ‰á‰µ á‰ áŠ á‹µáˆšáŠ• á‹¨á‰°áˆ¨áŒ‹áŒˆáŒ¡ á‹°áˆ‹áˆŽá‰½/áŠ á‰…áˆ«á‰¢á‹Žá‰½ á‰¥á‰» áŠ“á‰¸á‹!**",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    parts = query.data.split('_')
    if len(parts) < 3:
        await query.message.reply_text("âŒ á‹¨á‰°áˆ³áˆ³á‰° áˆ˜áˆ¨áŒƒ á‰°áˆ‹áŠ³áˆá¢")
        return ConversationHandler.END

    req_id = parts[2]
    buyer_id = parts[3] if len(parts) >= 4 else None

    if not buyer_id:
        listing = get_listing_by_id(int(req_id)) if req_id.isdigit() else None
        if listing:
            buyer_id = listing.get('user_chat_id')

    if not buyer_id:
        await query.message.reply_text("âŒ á‹¨áˆáˆ‹áŒŠá‹ áˆ˜áˆ¨áŒƒ áŠ áˆá‰°áŒˆáŠ˜áˆá¢")
        return ConversationHandler.END

    context.user_data['target_req_id'] = req_id
    context.user_data['target_buyer_id'] = buyer_id

    await query.message.reply_text(
        f"âœ… **áŒ¥á‹«á‰„ #ADK-{req_id}**\n\n"
        f"âœï¸ **á‹«áˆˆá‹Žá‰µáŠ• áŠ•á‰¥áˆ¨á‰µ á‹áˆ­á‹áˆ­ áˆ˜áˆ¨áŒƒ áŠ¥áŠ“ á‹‹áŒ‹ á‹«áˆµáŒˆá‰¡á¦**\n\n"
        f"ðŸ’¡ *áˆáˆ³áˆŒá¦* á‰¶á‹®á‰³ á‰ªá‰µá‹ 2021á£ 30,000 KMá£ á‹‹áŒ‹ 2.4 áˆšáˆŠá‹®áŠ•á£ áˆµáˆáŠ­ 0911...",
        reply_markup=ReplyKeyboardMarkup([["ðŸ  á‹‹áŠ“ áŒˆáŒ½"]], resize_keyboard=True),
        parse_mode="Markdown"
    )
    return BROKER_OFFER_TEXT


async def broker_offer_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "ðŸ  á‹‹áŠ“ áŒˆáŒ½":
        return await go_home(update, context)

    context.user_data['offer_text'] = text
    await update.message.reply_text(
        "ðŸ“¸ **á‹¨áŠ•á‰¥áˆ¨á‰±áŠ• áŽá‰¶ á‹­áˆ‹áŠ©á¦**\n\n"
        "(áŽá‰¶ áŠ¨áˆŒáˆá‹Žá‰µ 'áŽá‰¶ á‹¨áˆˆá‹áˆ' á‰¥áˆˆá‹ á‹­áŒ»á‰)",
        reply_markup=ReplyKeyboardMarkup([["áŽá‰¶ á‹¨áˆˆá‹áˆ"], ["ðŸ  á‹‹áŠ“ áŒˆáŒ½"]], resize_keyboard=True),
        parse_mode="Markdown"
    )
    return BROKER_OFFER_PHOTO


async def broker_offer_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text == "ðŸ  á‹‹áŠ“ áŒˆáŒ½":
        return await go_home(update, context)

    raw_buyer_id = context.user_data.get('target_buyer_id')
    req_id = context.user_data.get('target_req_id')
    offer_text = context.user_data.get('offer_text')

    if not raw_buyer_id or not req_id or not offer_text:
        await update.message.reply_text(
            "âŒ á‹¨áˆ‚á‹°á‰µ áˆµáˆ…á‰°á‰µ á‰°áŠ¨áˆ°á‰·áˆá¢ áŠ¥á‰£áŠ­á‹Ž áŠ¥áŠ•á‹°áŒˆáŠ“ á‹­áˆžáŠ­áˆ©á¢",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return ConversationHandler.END

    buyer_id = int(raw_buyer_id)
    broker_user = update.effective_user
    broker = get_broker(broker_user.id)
    broker_name = broker.get('full_name') if broker else (broker_user.first_name or "á‹°áˆ‹áˆ‹/áŠ á‰…áˆ«á‰¢")
    broker_phone = broker.get('phone', 'áŠ áˆá‰°áŒ á‰€áˆ°áˆ') if broker else 'áŠ áˆá‰°áŒ á‰€áˆ°áˆ'

    message_to_buyer = (
        f"ðŸŽ‰ **áˆˆáŒ¥á‹«á‰„á‹Ž (#ADK-{req_id}) áŠ á‹²áˆµ á‹¨á‰€áˆ¨á‰  áŠ áˆ›áˆ«áŒ­ áŠ áˆˆ!**\n\n"
        f"ðŸ‘¤ **á‹°áˆ‹áˆ‹/áŠ á‰…áˆ«á‰¢á¦** {broker_name}\n"
        f"ðŸ“ž **áˆµáˆáŠ­á¦** `{broker_phone}`\n\n"
        f"ðŸ“ **á‹¨áŠ•á‰¥áˆ¨á‰± á‹áˆ­á‹áˆ­á¦**\n{offer_text}\n\n"
        f"ðŸ’¡ *áŠ¨áˆáˆˆáŒ‰ á‹°á‹áˆˆá‹ áˆ˜áŒˆá‰ á‹«á‹¨á‰µ á‹­á‰½áˆ‹áˆ‰!*"
    )

    try:
        photo_id = None
        if update.message.photo:
            photo_id = update.message.photo[-1].file_id

        save_broker_offer(int(req_id), broker_user.id, offer_text, photo_id)

        if photo_id:
            await context.bot.send_photo(
                chat_id=buyer_id,
                photo=photo_id,
                caption=message_to_buyer,
                parse_mode="Markdown"
            )
        else:
            await context.bot.send_message(
                chat_id=buyer_id,
                text=message_to_buyer,
                parse_mode="Markdown"
            )

        await update.message.reply_text(
            "âœ… **áˆ˜áˆ¨áŒƒá‹Ž áˆˆáˆáˆ‹áŒŠá‹ á‰ áˆµáŠ¬á‰µ á‰°áˆáŠ³áˆ!**",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to send offer to buyer {buyer_id}: {e}")
        await update.message.reply_text(
            "âŒ áˆ˜áˆ¨áŒƒá‹áŠ• áˆˆáˆáˆ‹áŒŠá‹ áˆ˜áˆ‹áŠ­ áŠ áˆá‰°á‰»áˆˆáˆá¢",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )

    context.user_data.clear()
    return ConversationHandler.END


async def have_buyer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """á‹°áˆ‹áˆ‹ 'áŒˆá‹¢/á‰°áŠ¨áˆ«á‹­ áŠ áˆˆáŠ' áˆ²áŒ«áŠ• - áˆ»áŒ­ áˆ›áˆµá‰³á‹ˆá‰‚á‹« áˆ‹á‹­"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    broker = get_broker(user_id)

    if not broker or broker.get('status') != 'approved':
        await query.answer("â›” á‹¨á‰°áˆ¨áŒ‹áŒˆáŒ¡ á‹°áˆ‹áˆŽá‰½ á‰¥á‰» áŠá‹!", show_alert=True)
        return

    parts = query.data.split('_')
    if len(parts) < 3:
        await query.answer("âŒ á‹¨á‰°áˆ³áˆ³á‰° áˆ˜áˆ¨áŒƒ", show_alert=True)
        return

    item_id = parts[2]
    owner_id = parts[3] if len(parts) >= 4 else None

    listing = get_listing_by_id(int(item_id)) if item_id.isdigit() else None
    if not listing:
        await query.answer("âŒ áˆ›áˆµá‰³á‹ˆá‰‚á‹«á‹ áŠ áˆá‰°áŒˆáŠ˜áˆá¢", show_alert=True)
        return

    phone = listing.get('phone', '')
    owner_name = listing.get('user_name', 'á‰£áˆˆá‰¤á‰µ')

    # áˆµáˆáŠ­ áŠ«áˆˆ á‰€áŒ¥á‰³ áˆ˜á‹°á‹ˆá‹« á‰áˆá
    keyboard = []
    if phone and not str(phone).startswith("@"):
        # Telegram tel: link
        clean_phone = phone.replace(' ', '').replace('-', '')
        keyboard.append([InlineKeyboardButton(f"ðŸ“ž á‹°á‹áˆ {phone}", url=f"tel:{clean_phone}")])
    
    keyboard.append([InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")])

    text = (
        f"ðŸ¤ **áŒˆá‹¢/á‰°áŠ¨áˆ«á‹­ áŠ áˆˆá‹Žá‰µ**\n\n"
        f"ðŸ“¦ áˆ›áˆµá‰³á‹ˆá‰‚á‹«: #ADK-{item_id}\n"
        f"ðŸ‘¤ á‰£áˆˆá‰¤á‰µ: {owner_name}\n"
        f"ðŸ“ž áˆµáˆáŠ­: `{phone}`\n\n"
        f"ðŸ’¡ áŠ¨á‰³á‰½ á‹«áˆˆá‹áŠ• á‰áˆá á‰ áˆ˜áŒ«áŠ• á‰ á‰€áŒ¥á‰³ áˆ˜á‹°á‹ˆáˆ á‹­á‰½áˆ‹áˆ‰á¢"
    )

    try:
        await query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception:
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )


async def want_myself_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """á‹°áˆ‹áˆ‹ 'áˆˆáˆ«áˆ´ áŠ¥áˆáˆáŒˆá‹‹áˆˆáˆ' áˆ²áŒ«áŠ•"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    parts = query.data.split('_')
    item_id = parts[2] if len(parts) >= 3 else "?"

    listing = get_listing_by_id(int(item_id)) if str(item_id).isdigit() else None
    phone = listing.get('phone', 'áŠ áˆá‰°áŒˆáŠ˜áˆ') if listing else 'áŠ áˆá‰°áŒˆáŠ˜áˆ'

    await query.answer(f"ðŸ“ž áˆµáˆáŠ­: {phone}", show_alert=True)

    try:
        await query.edit_message_text(
            f"ðŸ‘¤ **áˆˆáˆ«áˆµá‹Ž á‹­áˆáˆáŒ‹áˆ‰**\n\n"
            f"ðŸ“¦ áˆ›áˆµá‰³á‹ˆá‰‚á‹«: #ADK-{item_id}\n"
            f"ðŸ“ž á‹¨á‰£áˆˆá‰¤á‰± áˆµáˆáŠ­: `{phone}`\n\n"
            f"ðŸ’¡ á‰ á‰€áŒ¥á‰³ á‹°á‹áˆˆá‹ áˆ˜áŒˆá‰ á‹«á‹¨á‰µ á‹­á‰½áˆ‹áˆ‰á¢",
            parse_mode="Markdown"
        )
    except Exception:
        pass
# ==============================================================================
# 13. VIEW REQUESTS / MARKETPLACE / DIRECTORY
# ==============================================================================

async def view_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_CHAT_ID_INT)
    broker = get_broker(user_id)

    if not is_admin and not broker:
        await update.message.reply_text(
            "â›” á‹­áˆ…áŠ• áŒˆáŒ½ áˆ›á‹¨á‰µ á‹¨áˆšá‰½áˆ‰á‰µ á‹¨á‰°áˆ˜á‹˜áŒˆá‰¡ áŠ á‰…áˆ«á‰¢á‹Žá‰½/á‹°áˆ‹áˆŽá‰½ á‹ˆá‹­áˆ áŠ á‹µáˆšáŠ• á‰¥á‰» áŠ“á‰¸á‹!\n\n"
            "ðŸ“ áŠ¥á‰£áŠ­á‹ŽáŠ• áˆ˜áŒ€áˆ˜áˆªá‹« 'ðŸ“ áŠ¥áŠ•á‹° áŠ á‰…áˆ«á‰¢/á‹°áˆ‹áˆ‹ áˆ˜áˆ˜á‹áŒˆá‰¥' á‹­áŒ«áŠ‘á¢",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return

    if not is_admin and broker.get('status') != 'approved':
        await update.message.reply_text(
            "â³ **áˆá‹áŒˆá‰£á‹Ž áŒˆáŠ“ á‰ áŠ á‹µáˆšáŠ• áŠ áˆáŒ¸á‹°á‰€áˆ!**",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
        return

    listings = get_listings_by_category(limit=20, offset=0, req_type="BUY")
    total = count_listings(req_type="BUY")

    if not listings:
        await update.message.reply_text(
            "ðŸ“­ **áˆáŠ•áˆ áŠ•á‰ áŒ¥á‹«á‰„á‹Žá‰½ á‹¨áˆ‰áˆ**",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
        return

    broker_name = "ðŸ‘‘ áŠ á‹µáˆšáŠ•" if is_admin else (broker.get('full_name') if broker else "á‹°áˆ‹áˆ‹")

    await update.message.reply_text(
        f"<b>ðŸ“‹ á‹¨áˆáˆ‹áŒŠá‹Žá‰½ á‹áˆ­á‹áˆ­</b>\n"
        f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
        f"ðŸ‘¤ <b>{broker_name}</b>\n"
        f"ðŸ”” <b>áŒ á‰…áˆ‹áˆ‹á¡</b> {total} áŒ¥á‹«á‰„á‹Žá‰½",
        parse_mode="HTML"
    )

    for listing in listings:
        req_id = listing.get('id')
        user_chat_id = listing.get('user_chat_id')
        card_text = format_buyer_card(listing)
        
        reply_markup = build_request_keyboard(req_id, user_chat_id)

        await update.message.reply_text(
            card_text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

async def view_public_marketplace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = get_public_marketplace_items(limit=10)
    user_id = update.effective_user.id

    if not items:
        await update.message.reply_text(
            "ðŸ“­ **á‰ áŠ áˆáŠ‘ áˆ°á‹“á‰µ áˆˆáˆ½á‹«áŒ­/áŠªáˆ«á‹­ á‹¨á‰€áˆ¨á‰¡ áŠ•á‰¥áˆ¨á‰¶á‰½ á‹¨áˆ‰áˆá¢**",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        "ðŸ›ï¸ **áˆˆáˆ½á‹«áŒ­ áŠ¥áŠ“ áˆˆáŠªáˆ«á‹­ á‹¨á‰€áˆ¨á‰¡ áŠ•á‰¥áˆ¨á‰¶á‰½ á‹áˆ­á‹áˆ­á¦**",
        parse_mode="Markdown"
    )

    for item in items:
        card_text = format_seller_card(item)
        photo_id = item.get('photo_id')
        owner_id = item.get('user_chat_id')
        phone = item.get('phone', '')
        
        reply_markup = build_seller_card_keyboard(
            item_id=item.get('id'),
            owner_id=owner_id,
            current_user_id=user_id,
            phone=phone
        )

        if photo_id:
            try:
                await update.message.reply_photo(
                    photo=photo_id, 
                    caption=card_text, 
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
            except Exception:
                await update.message.reply_text(card_text, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await update.message.reply_text(card_text, reply_markup=reply_markup, parse_mode="Markdown")

async def view_brokers_directory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(sc, callback_data=f"dir_sc_{sc}")] for sc in SUB_CITIES]
    keyboard.append([InlineKeyboardButton("ðŸŒ á‹¨áˆáˆ‰áˆ áŠ­ááˆˆ áŠ¨á‰°áˆžá‰½", callback_data="dir_sc_áˆáˆ‰áˆ")])
    keyboard.append([InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")])

    await update.message.reply_text(
        "ðŸ“ **á‹¨á‹°áˆ‹áˆŽá‰½áŠ“ áŠ á‰…áˆ«á‰¢á‹Žá‰½ áˆ›á‹áŒ«**\n\náŠ¥á‰£áŠ­á‹ŽáŠ• áˆ›á‹¨á‰µ á‹¨áˆšáˆáˆáŒ‰á‰ á‰µáŠ• áŠ­ááˆˆ áŠ¨á‰°áˆ› á‹­áˆáˆ¨áŒ¡á¦",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def filter_brokers_by_subcity_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    sub_city = query.data.replace("dir_sc_", "")
    brokers = get_approved_brokers_directory(sub_city=sub_city)

    if not brokers:
        await query.edit_message_text(f"ðŸ“­ á‰ {sub_city} áŠ­ááˆˆ áŠ¨á‰°áˆ› á‹¨á‰°áˆ˜á‹˜áŒˆá‰¡ á‹°áˆ‹áˆŽá‰½ áŠ áˆá‰°áŒˆáŠ™áˆá¢")
        return

    msg = f"ðŸ“‹ **á‹¨á‰°áˆ¨áŒ‹áŒˆáŒ¡ á‹°áˆ‹áˆŽá‰½ á‹áˆ­á‹áˆ­ ({sub_city})á¦**\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n\n"
    for b in brokers:
        msg += format_broker_profile(b) + "\n\n"

    await query.edit_message_text(msg, parse_mode="Markdown")
# ==============================================================================
# 14. ADMIN HANDLERS
# ==============================================================================

async def admin_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if update.effective_user.id != ADMIN_CHAT_ID_INT:
        await query.answer("â›” á‹­áˆ…áŠ• áˆ›á‹µáˆ¨áŒ á‹¨áˆšá‰½áˆ‰á‰µ áŠ á‹µáˆšáŠ• á‰¥á‰» áŠ“á‰¸á‹!", show_alert=True)
        return

    if data.startswith("admin_appr_"):
        broker_telegram_id = int(data.replace("admin_appr_", ""))
        success = update_broker_status(broker_telegram_id, "approved")
        if success:
            try:
                await query.edit_message_caption(
                    caption=f"{query.message.caption}\n\nâœ… **áˆáŠ”á‰³á¦ á‰°á€á‹µá‰‹áˆ (Approved)**",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            try:
                await context.bot.send_message(
                    chat_id=broker_telegram_id,
                    text=(
                        "ðŸŽ‰ **áŠ¥áŠ•áŠ³áŠ• á‹°áˆµ áŠ áˆˆá‹Žá‰µ!**\n\n"
                        "á‹¨á‹°áˆ‹áˆ‹/áŠ á‰…áˆ«á‰¢ áˆá‹áŒˆá‰£á‹Ž á‰ áŠ á‹µáˆšáŠ• á€á‹µá‰‹áˆá¢\n"
                        "áŠ áˆáŠ• 'ðŸ“‹ á‹¨áˆáˆ‹áŒŠá‹Žá‰½ á‹áˆ­á‹áˆ­' á‰ áˆ˜áŒ«áŠ• áˆ˜áˆµáˆ«á‰µ áˆ˜áŒ€áˆ˜áˆ­ á‹­á‰½áˆ‹áˆ‰á¢"
                    ),
                    reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Failed to notify approved broker: {e}")
        else:
            await query.message.reply_text("âŒ á‹¨á‹°áˆ‹áˆ‹á‹áŠ• áˆáŠ”á‰³ áˆ˜á‰€á‹¨áˆ­ áŠ áˆá‰°á‰»áˆˆáˆá¢")

    elif data.startswith("admin_reje_"):
        broker_telegram_id = int(data.replace("admin_reje_", ""))
        success = update_broker_status(broker_telegram_id, "rejected")
        if success:
            try:
                await query.edit_message_caption(
                    caption=f"{query.message.caption}\n\nâŒ **áˆáŠ”á‰³á¦ á‰°áˆ°áˆ­á‹Ÿáˆ (Rejected)**",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            try:
                await context.bot.send_message(
                    chat_id=broker_telegram_id,
                    text="âŒ **á‹¨áˆá‹áŒˆá‰£ áŒ¥á‹«á‰„á‹Ž á‹á‹µá‰… á‰°á‹°áˆ­áŒ“áˆ!** áŠ¥á‰£áŠ­á‹Ž áŠ¥áŠ•á‹°áŒˆáŠ“ á‹­áˆ˜á‹áŒˆá‰¡á¢",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Failed to notify rejected broker: {e}")

async def delete_request_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_CHAT_ID_INT)

    parts = query.data.split('_')
    if len(parts) < 3:
        await query.message.reply_text("âŒ á‹¨á‰°áˆ³áˆ³á‰° áˆ˜áˆ¨áŒƒ á‰°áˆ‹áŠ³áˆá¢")
        return

    req_id = int(parts[-1])
    listing = get_listing_by_id(req_id)

    if not listing:
        await query.message.reply_text("âŒ áŒ¥á‹«á‰„á‹ áŠ áˆá‰°áŒˆáŠ˜áˆá¢")
        return

    if not is_admin and listing.get('user_chat_id') != user_id:
        await query.message.reply_text("â›” á‹­áˆ…áŠ• áŒ¥á‹«á‰„ á‹¨áˆ›áŒ¥á‹á‰µ áˆá‰ƒá‹µ á‹¨áˆˆá‹Žá‰µáˆ!")
        return

    success = update_listing_status(req_id, "deleted")
    if success:
        try:
            await query.edit_message_text(
                f"ðŸ—‘ï¸ **áŒ¥á‹«á‰„ #{req_id} á‰ áˆµáŠ¬á‰µ á‰°áˆ°áˆ­á‹Ÿáˆá¢**",
                parse_mode="Markdown"
            )
        except Exception:
            await query.message.reply_text(
                f"ðŸ—‘ï¸ **áŒ¥á‹«á‰„ #{req_id} á‰ áˆµáŠ¬á‰µ á‰°áˆ°áˆ­á‹Ÿáˆá¢**",
                parse_mode="Markdown"
            )
    else:
        await query.message.reply_text("âŒ áŒ¥á‹«á‰„á‹áŠ• áˆ›áŒ¥á‹á‰µ áŠ áˆá‰°á‰»áˆˆáˆá¢")
        # ==============================================================================
# 14B. FAVORITES, SOLD MARKER & NOTIFICATION PREFERENCES
# ==============================================================================

async def view_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
   """á‹¨á‰°áŒ á‰ƒáˆšá‹áŠ• á‹¨á‰°á‹ˆá‹³áŒ†á‰½ á‹áˆ­á‹áˆ­ á‹«áˆ³á‹«áˆ"""
   user_id = update.effective_user.id
   favorites = get_user_favorites(user_id)
   
   if not favorites:
       await update.message.reply_text(
           "â¤ï¸ **á‹¨á‰°á‹ˆá‹³áŒ†á‰½ á‹áˆ­á‹áˆ­**\n\n"
           "ðŸ“­ áŠ¥áˆµáŠ«áˆáŠ• áˆáŠ•áˆ á‹¨á‰°á‹ˆá‹³áŒ… áˆ›áˆµá‰³á‹ˆá‰‚á‹« áŠ áˆ‹áˆµá‰€áˆ˜áŒ¡áˆá¢\n\n"
           "ðŸ’¡ áˆ›áˆµá‰³á‹ˆá‰‚á‹«á‹Žá‰½áŠ• áˆ²á‹«á‹© áŠ¨áˆµáˆ© á‹«áˆˆá‹áŠ• 'â¤ï¸ á‹ˆá‹° á‰°á‹ˆá‹³áŒ†á‰½ áŒ¨áˆáˆ­' á‹¨áˆšáˆˆá‹áŠ• á‹­áŒ«áŠ‘á¢",
           reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
           parse_mode="Markdown"
       )
       return
   
   await update.message.reply_text(
       f"â¤ï¸ **á‹¨á‰°á‹ˆá‹³áŒ†á‰½ á‹áˆ­á‹áˆ­** ({len(favorites)} áŠ•á‰¥áˆ¨á‰¶á‰½)\n"
       f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”",
       parse_mode="Markdown"
   )
   
   for item in favorites:
       card_text = format_seller_card(item)
       is_fav = True
       reply_markup = build_seller_card_keyboard(item['id'], user_id, is_fav)
       
       photos = item.get('photos', [])
       if photos:
           try:
               await update.message.reply_photo(
                   photo=photos[0],
                   caption=card_text,
                   reply_markup=reply_markup,
                   parse_mode="Markdown"
               )
           except Exception:
               await update.message.reply_text(card_text, reply_markup=reply_markup, parse_mode="Markdown")
       else:
           await update.message.reply_text(card_text, reply_markup=reply_markup, parse_mode="Markdown")


async def toggle_favorite_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
   """Favorite áˆ˜áŒ¨áˆ˜áˆ­/áˆ›áˆµá‹ˆáŒˆá‹µ"""
   query = update.callback_query
   await query.answer()
   
   user_id = update.effective_user.id
   data = query.data
   
   if data.startswith("fav_add_"):
       listing_id = int(data.replace("fav_add_", ""))
       success = add_favorite(user_id, listing_id)
       if success:
           await query.answer("â¤ï¸ á‹ˆá‹° á‰°á‹ˆá‹³áŒ†á‰½ á‰°áŒ¨áˆáˆ¯áˆ!", show_alert=False)
           # áŠ á‹áˆ«áˆ©áŠ• á‹ˆá‹° remove á‹­á‰€á‹­áˆ©
           listing = get_listing_by_id(listing_id)
           if listing:
               is_fav = True
               new_markup = build_seller_card_keyboard(listing_id, listing.get('user_chat_id', user_id), is_fav)
               try:
                   await query.edit_message_reply_markup(reply_markup=new_markup)
               except Exception:
                   pass
       else:
           await query.answer("âŒ áˆµáˆ…á‰°á‰µ á‰°áŠ¨áˆµá‰·áˆá¢", show_alert=True)
   
   elif data.startswith("fav_remove_"):
       listing_id = int(data.replace("fav_remove_", ""))
       success = remove_favorite(user_id, listing_id)
       if success:
           await query.answer("ðŸ’” áŠ¨á‰°á‹ˆá‹³áŒ†á‰½ á‰°á‹ˆáŒá‹·áˆ!", show_alert=False)
           listing = get_listing_by_id(listing_id)
           if listing:
               is_fav = False
               new_markup = build_seller_card_keyboard(listing_id, listing.get('user_chat_id', user_id), is_fav)
               try:
                   await query.edit_message_reply_markup(reply_markup=new_markup)
               except Exception:
                   pass
       else:
           await query.answer("âŒ áˆµáˆ…á‰°á‰µ á‰°áŠ¨áˆµá‰·áˆá¢", show_alert=True)


async def mark_sold_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
   """áˆ›áˆµá‰³á‹ˆá‰‚á‹«áŠ• áŠ¥áŠ•á‹°á‰°áˆ¸áŒ /á‰°áŠ¨áˆ«á‹¨ áˆ›á‹µáˆ¨áŒ"""
   query = update.callback_query
   await query.answer()
   
   user_id = update.effective_user.id
   data = query.data
   listing_id = int(data.replace("mark_sold_", ""))
   
   listing = get_listing_by_id(listing_id)
   if not listing:
       await query.answer("âŒ áˆ›áˆµá‰³á‹ˆá‰‚á‹«á‹ áŠ áˆá‰°áŒˆáŠ˜áˆá¢", show_alert=True)
       return
   
   # á‹¨áˆ›áˆµá‰³á‹ˆá‰‚á‹«á‹ á‰£áˆˆá‰¤á‰µ á‰¥á‰» áˆ›áˆ­áŠ­ áˆ›á‹µáˆ¨áŒ á‹­á‰½áˆ‹áˆ
   if listing.get('user_chat_id') != user_id:
       await query.answer("â›” á‹­áˆ…áŠ• áˆ›á‹µáˆ¨áŒ á‹¨áˆšá‰½áˆ‰á‰µ á‹¨áˆ›áˆµá‰³á‹ˆá‰‚á‹«á‹ á‰£áˆˆá‰¤á‰µ á‰¥á‰» áŠá‹!", show_alert=True)
       return
   
   success = update_listing_status(listing_id, "sold")
   if success:
       try:
           await query.edit_message_caption(
               caption=f"{query.message.caption}\n\nâœ… **á‹­áˆ… áŠ•á‰¥áˆ¨á‰µ á‰°áˆ¸áŒ§áˆ/á‰°áŠ¨áˆ«á‹­á‰·áˆ!**",
               parse_mode="Markdown"
           )
       except Exception:
           await query.edit_message_text(
               f"âœ… **áˆ›áˆµá‰³á‹ˆá‰‚á‹« #ADK-{listing_id} áŠ¥áŠ•á‹°á‰°áˆ¸áŒ /áŠ¥áŠ•á‹°á‰°áŠ¨áˆ«á‹¨ áˆáˆáŠ­á‰µ á‰°á‹°áˆ­áŒŽá‰ á‰³áˆ!**",
               parse_mode="Markdown"
           )
       await query.answer("âœ… áˆ›áˆµá‰³á‹ˆá‰‚á‹«á‹ áŠ¥áŠ•á‹°á‰°áˆ¸áŒ  áˆáˆáŠ­á‰µ á‰°á‹°áˆ­áŒŽá‰ á‰³áˆ!", show_alert=True)
   else:
       await query.answer("âŒ áˆµáˆ…á‰°á‰µ á‰°áŠ¨áˆµá‰·áˆá¢", show_alert=True)


async def need_item_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
   """á‹°áˆ‹áˆ‹ áˆˆáˆ«áˆ± áˆ²áˆáˆáŒ"""
   query = update.callback_query
   await query.answer()
   
   user_id = update.effective_user.id
   data = query.data
   parts = data.split('_')
   req_id = parts[2] if len(parts) >= 3 else "?"
   buyer_id = parts[3] if len(parts) >= 4 else user_id
   
   broker = get_broker(user_id)
   broker_name = broker.get('full_name', 'á‹°áˆ‹áˆ‹') if broker else 'á‰°áŒ á‰ƒáˆš'
   
   await query.message.reply_text(
       f"ðŸ‘¤ **{broker_name}** áŠ¥áˆ­áˆµá‹Ž áˆˆáˆ«áˆµá‹Ž á‹­áˆ…áŠ• áŠ•á‰¥áˆ¨á‰µ á‹­áˆáˆáŒ‹áˆ‰á¢\n\n"
       f"ðŸ“ž áŠ¥á‰£áŠ­á‹Ž á‹¨áˆ›áˆµá‰³á‹ˆá‰‚á‹«á‹áŠ• á‰£áˆˆá‰¤á‰µ á‰ á‰€áŒ¥á‰³ á‹«áŒáŠ™á¢",
       parse_mode="Markdown"
   )
   
   # áˆˆáŒˆá‹¢á‹ áˆ›áˆ³á‹ˆá‰…
   try:
       await context.bot.send_message(
           chat_id=int(buyer_id),
           text=f"ðŸ‘¤ **{broker_name}** á‹¨áŠ¥áˆ­áˆµá‹ŽáŠ• áŒ¥á‹«á‰„ #ADK-{req_id} áŠ á‹­á‰¶á‰³áˆá¢\n\n"
                f"ðŸ’¡ áˆˆáˆ«áˆ³á‰¸á‹ á‹­áˆ…áŠ• áŠ•á‰¥áˆ¨á‰µ á‹­áˆáˆáŒ‹áˆ‰á¢",
           parse_mode="Markdown"
       )
   except Exception as e:
       logger.error(f"Failed to notify buyer: {e}")


async def view_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
   """á‹¨áˆ›áˆµá‰³á‹ˆá‰‚á‹« á‹áˆ­á‹áˆ­ áŠ¥á‹­á‰³"""
   query = update.callback_query
   await query.answer()
   
   data = query.data
   listing_id = int(data.replace("view_detail_", ""))
   
   listing = get_listing_by_id(listing_id)
   if not listing:
       await query.answer("âŒ áˆ›áˆµá‰³á‹ˆá‰‚á‹«á‹ áŠ áˆá‰°áŒˆáŠ˜áˆá¢", show_alert=True)
       return
   
   card_text = format_seller_card(listing)
   user_id = update.effective_user.id
   is_fav = is_favorite(user_id, listing_id)
   reply_markup = build_seller_card_keyboard(listing_id, listing.get('user_chat_id', user_id), is_fav)
   
   photos = listing.get('photos', [])
   if photos:
       await context.bot.send_photo(
           chat_id=user_id,
           photo=photos[0],
           caption=card_text,
           reply_markup=reply_markup,
           parse_mode="Markdown"
       )
   else:
       await context.bot.send_message(
           chat_id=user_id,
           text=card_text,
           reply_markup=reply_markup,
           parse_mode="Markdown"
       )


# ========== NOTIFICATION PREFERENCES ==========

async def notification_prefs_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
   """á‹¨áˆ›áˆ³á‹ˆá‰‚á‹« áˆáˆ­áŒ« áˆ›áˆµá‰°áŠ«áŠ¨á‹« áˆ˜áŠ­áˆá‰»"""
   user_id = update.effective_user.id
   broker = get_broker(user_id)
   
   if not broker:
       await update.message.reply_text(
           "â›” á‹­áˆ…áŠ• áˆ›á‹µáˆ¨áŒ á‹¨áˆšá‰½áˆ‰á‰µ á‹¨á‰°áˆ˜á‹˜áŒˆá‰¡ á‹°áˆ‹áˆŽá‰½/áŠ á‰…áˆ«á‰¢á‹Žá‰½ á‰¥á‰» áŠ“á‰¸á‹!",
           reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
       )
       return
   
   prefs = broker.get('notification_prefs', {})
   if isinstance(prefs, str):
       try: prefs = json.loads(prefs)
       except: prefs = {"car": True, "house": True, "price_min": 0, "price_max": 999999999, "enabled": True}
   
   enabled_text = "âœ… á‰ áˆ­á‰°á‹‹áˆ" if prefs.get('enabled', True) else "âŒ áŒ áá‰°á‹‹áˆ"
   car_text = "âœ…" if prefs.get('car', True) else "âŒ"
   house_text = "âœ…" if prefs.get('house', True) else "âŒ"
   
   keyboard = [
       [InlineKeyboardButton(f"ðŸ”” áˆ›áˆ³á‹ˆá‰‚á‹«á‹Žá‰½á¦ {enabled_text}", callback_data="notif_pref_toggle")],
       [InlineKeyboardButton(f"ðŸš— áˆ˜áŠªáŠ“á¦ {car_text}", callback_data="notif_pref_car"),
        InlineKeyboardButton(f"ðŸ  á‰¤á‰µá¦ {house_text}", callback_data="notif_pref_house")],
       [InlineKeyboardButton("ðŸ’° á‹¨á‹‹áŒ‹ áŠ­áˆáˆ áŠ áˆµá‰°áŠ«áŠ­áˆ", callback_data="notif_pref_price")],
       [InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")]
   ]
   
   await update.message.reply_text(
       f"âš™ï¸ **á‹¨áˆ›áˆ³á‹ˆá‰‚á‹« áˆáˆ­áŒ«á‹Žá‰½**\n\n"
       f"ðŸ”” **áˆáŠ”á‰³á¦** {enabled_text}\n"
       f"ðŸš— **áˆ˜áŠªáŠ“á¦** {car_text}\n"
       f"ðŸ  **á‰¤á‰µá¦** {house_text}\n"
       f"ðŸ’° **á‹¨á‹‹áŒ‹ áŠ­áˆáˆá¦** {prefs.get('price_min', 0):,} - {prefs.get('price_max', 999999999):,} á‰¥áˆ­\n\n"
       f"áŠ¨á‰³á‰½ á‹«áˆ‰á‰µáŠ• á‰áˆáŽá‰½ á‰ áˆ˜áŒ á‰€áˆ áˆ›áˆµá‰°áŠ«áŠ¨áˆ á‹­á‰½áˆ‹áˆ‰á¢",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )


async def notification_prefs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
   """á‹¨áˆ›áˆ³á‹ˆá‰‚á‹« áˆáˆ­áŒ« á‰áˆáŽá‰½ áˆáˆ‹áˆ½"""
   query = update.callback_query
   await query.answer()
   
   user_id = update.effective_user.id
   broker = get_broker(user_id)
   
   if not broker:
       await query.answer("â›” áŠ áˆá‰°áˆá‰€á‹°áˆ!", show_alert=True)
       return
   
   prefs = broker.get('notification_prefs', {})
   if isinstance(prefs, str):
       try: prefs = json.loads(prefs)
       except: prefs = {"car": True, "house": True, "price_min": 0, "price_max": 999999999, "enabled": True}
   
   data = query.data
   
   if data == "notif_pref_toggle":
       prefs['enabled'] = not prefs.get('enabled', True)
   elif data == "notif_pref_car":
       prefs['car'] = not prefs.get('car', True)
   elif data == "notif_pref_house":
       prefs['house'] = not prefs.get('house', True)
   
   update_broker_notification_prefs(user_id, prefs)
   
   # áˆ˜áˆáŠ¥áŠ­á‰±áŠ• áˆ›á‹˜áˆ˜áŠ•
   enabled_text = "âœ… á‰ áˆ­á‰°á‹‹áˆ" if prefs.get('enabled', True) else "âŒ áŒ áá‰°á‹‹áˆ"
   car_text = "âœ…" if prefs.get('car', True) else "âŒ"
   house_text = "âœ…" if prefs.get('house', True) else "âŒ"
   
   keyboard = [
       [InlineKeyboardButton(f"ðŸ”” áˆ›áˆ³á‹ˆá‰‚á‹«á‹Žá‰½á¦ {enabled_text}", callback_data="notif_pref_toggle")],
       [InlineKeyboardButton(f"ðŸš— áˆ˜áŠªáŠ“á¦ {car_text}", callback_data="notif_pref_car"),
        InlineKeyboardButton(f"ðŸ  á‰¤á‰µá¦ {house_text}", callback_data="notif_pref_house")],
       [InlineKeyboardButton("ðŸ’° á‹¨á‹‹áŒ‹ áŠ­áˆáˆ áŠ áˆµá‰°áŠ«áŠ­áˆ", callback_data="notif_pref_price")],
       [InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")]
   ]
   
   try:
       await query.edit_message_text(
           f"âš™ï¸ **á‹¨áˆ›áˆ³á‹ˆá‰‚á‹« áˆáˆ­áŒ«á‹Žá‰½**\n\n"
           f"ðŸ”” **áˆáŠ”á‰³á¦** {enabled_text}\n"
           f"ðŸš— **áˆ˜áŠªáŠ“á¦** {car_text}\n"
           f"ðŸ  **á‰¤á‰µá¦** {house_text}\n"
           f"ðŸ’° **á‹¨á‹‹áŒ‹ áŠ­áˆáˆá¦** {prefs.get('price_min', 0):,} - {prefs.get('price_max', 999999999):,} á‰¥áˆ­\n\n"
           f"áŠ¨á‰³á‰½ á‹«áˆ‰á‰µáŠ• á‰áˆáŽá‰½ á‰ áˆ˜áŒ á‰€áˆ áˆ›áˆµá‰°áŠ«áŠ¨áˆ á‹­á‰½áˆ‹áˆ‰á¢",
           reply_markup=InlineKeyboardMarkup(keyboard),
           parse_mode="Markdown"
       )
   except Exception:
       pass
       # ==============================================================================
# 14B. FAVORITES, SOLD MARKER & NOTIFICATION PREFERENCES
# ==============================================================================

async def nohave_item_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """á‹­áˆˆáˆáŠ - áˆ˜áˆáŠ¥áŠ­á‰±áŠ• áŠ¨á‹°áˆ‹áˆ‹á‹ á‰¥á‰» á‹«áŒ á‹áˆ"""
    query = update.callback_query
    user_id = query.from_user.id
    broker = get_broker(user_id)

    if not broker or broker.get('status') != 'approved':
        await query.answer("â›” á‹­áˆ…áŠ• áˆ›á‹µáˆ¨áŒ á‹¨áˆšá‰½áˆ‰á‰µ á‰ áŠ á‹µáˆšáŠ• á‹¨á‰°áˆ¨áŒ‹áŒˆáŒ¡ á‹°áˆ‹áˆŽá‰½ á‰¥á‰» áŠ“á‰¸á‹!", show_alert=True)
        return

    parts = query.data.split('_')
    req_id = parts[-1] if parts else "?"
    
    await query.answer(f"â„¹ï¸ áŒ¥á‹«á‰„ #{req_id} á‰°áˆˆááˆá¢", show_alert=False)
    
    try:
        await query.delete_message()
    except Exception:
        try:
            await query.edit_message_text(
                f"â­ï¸ **áŒ¥á‹«á‰„ #{req_id} á‰°áˆˆááˆá¢**",
                parse_mode="Markdown"
            )
        except Exception:
            pass


async def mark_sold_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """á‰°áˆ¸áŒ§áˆ / á‰°áŠ¨áˆ«á‹­á‰·áˆ - á‰£áˆˆá‰¤á‰± á‹ˆá‹­áˆ áŠ á‹µáˆšáŠ• á‰¥á‰»"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    listing_id = int(data.replace("mark_sold_", ""))
    
    listing = get_listing_by_id(listing_id)
    if not listing:
        await query.answer("âŒ áˆ›áˆµá‰³á‹ˆá‰‚á‹«á‹ áŠ áˆá‰°áŒˆáŠ˜áˆá¢", show_alert=True)
        return
    
    # á‰£áˆˆá‰¤á‰± á‹ˆá‹­áˆ áŠ á‹µáˆšáŠ• á‰¥á‰»
    if listing.get('user_chat_id') != user_id and user_id != ADMIN_CHAT_ID_INT:
        await query.answer("â›” á‹­áˆ…áŠ• áˆ›á‹µáˆ¨áŒ á‹¨áˆšá‰½áˆ‰á‰µ á‹¨áˆ›áˆµá‰³á‹ˆá‰‚á‹«á‹ á‰£áˆˆá‰¤á‰µ á‹ˆá‹­áˆ áŠ á‹µáˆšáŠ• á‰¥á‰» áŠá‹!", show_alert=True)
        return
    
    success = update_listing_status(listing_id, "sold")
    if success:
        try:
            await query.edit_message_caption(
                caption=f"{query.message.caption}\n\nâœ… **á‹­áˆ… áŠ•á‰¥áˆ¨á‰µ á‰°áˆ¸áŒ§áˆ/á‰°áŠ¨áˆ«á‹­á‰·áˆ!**",
                parse_mode="Markdown"
            )
        except Exception:
            await query.edit_message_text(
                f"âœ… **áˆ›áˆµá‰³á‹ˆá‰‚á‹« #ADK-{listing_id} áŠ¥áŠ•á‹°á‰°áˆ¸áŒ /áŠ¥áŠ•á‹°á‰°áŠ¨áˆ«á‹¨ áˆáˆáŠ­á‰µ á‰°á‹°áˆ­áŒŽá‰ á‰³áˆ!**",
                parse_mode="Markdown"
            )
        await query.answer("âœ… áˆ›áˆµá‰³á‹ˆá‰‚á‹«á‹ áŠ¥áŠ•á‹°á‰°áˆ¸áŒ  áˆáˆáŠ­á‰µ á‰°á‹°áˆ­áŒŽá‰ á‰³áˆ!", show_alert=True)
    else:
        await query.answer("âŒ áˆµáˆ…á‰°á‰µ á‰°áŠ¨áˆµá‰·áˆá¢", show_alert=True)

# ==============================================================================
# 15. SUPPORT HANDLER
# ==============================================================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "ðŸ“ž **áŠ á‹²áŠ« áˆ›áˆ­áŠ¬á‰µá•áˆŒáˆµ - á‹¨á‹°áŠ•á‰ áŠžá‰½ á‹µáŒ‹á**\n"
        "â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n\n"
        "â“ **á‰¦á‰±áŠ• áŠ¥áŠ•á‹´á‰µ áˆ˜áŒ á‰€áˆ á‹­á‰»áˆ‹áˆ?**\n\n"
        "1ï¸âƒ£ **áˆ˜áŒá‹›á‰µ / áˆ˜áŠ¨áˆ«á‹¨á‰µá¦** á‹¨áˆšáˆáˆáŒ‰á‰µáŠ• á‰¤á‰µ á‹ˆá‹­áˆ áˆ˜áŠªáŠ“ ááˆ‹áŒŽá‰µ á‹­áˆ˜á‹áŒá‰¡á¢\n"
        "2ï¸âƒ£ **áˆ˜áˆ¸áŒ¥ / áˆ›áŠ¨áˆ«á‹¨á‰µá¦** á‹¨áˆšáˆ¸áŒ¡á‰µáŠ• áŠ•á‰¥áˆ¨á‰µ áˆ˜áˆ¨áŒƒ áŠ¥áŠ“ áŽá‰¶ á‰ áˆ˜áŒ«áŠ• áˆˆáŒˆá‰ á‹« á‹«á‰…áˆ­á‰¡á¢\n"
        "3ï¸âƒ£ **á‹¨á‹°áˆ‹áˆŽá‰½ áˆ›á‹áŒ«á¦** á‰ á‹¨áŠ­ááˆˆ áŠ¨á‰°áˆ›á‹ á‹¨á‰°áˆ¨áŒ‹áŒˆáŒ¡ á‹°áˆ‹áˆŽá‰½áŠ• á‹­áˆ˜áˆáŠ¨á‰±á¢\n\n"
        "ðŸ“² **áˆˆá‰°áŒ¨áˆ›áˆª áŒ¥á‹«á‰„á¦** áŠ¨áŠ áˆµá‰°á‹³á‹³áˆªá‹ áŒ‹áˆ­ á‹­áŒˆáŠ“áŠ™á¢"
    )

    keyboard = [
        [InlineKeyboardButton("ðŸ’¬ áŠ¨áŠ áˆµá‰°á‹³á‹³áˆªá‹ áŒ‹áˆ­ á‹­á‹ˆá‹«á‹©", url="https://t.me/Adika_Admin")],
        [InlineKeyboardButton("ðŸ  á‹‹áŠ“ áŒˆáŒ½", callback_data="flow_home")]
    ]

    if update.message:
        await update.message.reply_text(help_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.edit_message_text(help_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
# ==============================================================================
# 16. MAIN ENGINE
# ==============================================================================

def main():
    global bot_app

    init_db()
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    bot_app = app

    cancel_filter = filters.Regex("^ðŸ  á‹‹áŠ“ áŒˆáŒ½$")
    cancel_handler = MessageHandler(cancel_filter, go_home)

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Buyer Conversation
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    buyer_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^ðŸ” áˆ˜áŒá‹›á‰µ / áˆ˜áŠ¨áˆ«á‹¨á‰µ$"), buyer_start)],
        states={
            BUYER_MAIN: [CallbackQueryHandler(buyer_category_chosen, pattern="^flow_buy_cat_"), cancel_handler],
            BUYER_ACTION: [CallbackQueryHandler(buyer_action_chosen, pattern="^flow_buy_action_"), cancel_handler],
            BUYER_SUB: [CallbackQueryHandler(buyer_sub_chosen, pattern="^flow_buy_sub_"), cancel_handler],
            BUYER_PROPERTY: [CallbackQueryHandler(buyer_property_chosen, pattern="^flow_buy_prop_"), cancel_handler],
            BUYER_HTYPE: [CallbackQueryHandler(buyer_htype_chosen, pattern="^flow_buy_htype_"), cancel_handler],
            BUYER_BUDGET_RANGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_budget_range), cancel_handler],
            BUYER_ALERT: [CallbackQueryHandler(buyer_alert_choice, pattern="^alert_"), cancel_handler],
            BUYER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_details), cancel_handler],
            BUYER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_phone), cancel_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_handler],
        allow_reentry=True,
    )

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Seller Conversation
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    seller_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^ðŸ“¢ áˆ˜áˆ¸áŒ¥ / áˆ›áŠ¨áˆ«á‹¨á‰µ$"), seller_start)],
        states={
            SELLER_MAIN: [CallbackQueryHandler(seller_category_chosen, pattern="^flow_sell_cat_"), cancel_handler],
            SELLER_ACTION: [CallbackQueryHandler(seller_action_chosen, pattern="^flow_sell_action_"), cancel_handler],
            SELLER_SUB: [CallbackQueryHandler(seller_sub_chosen, pattern="^flow_sell_sub_"), cancel_handler],
            SELLER_PROPERTY: [CallbackQueryHandler(seller_property_chosen, pattern="^flow_sell_prop_"), cancel_handler],
            SELLER_HTYPE: [CallbackQueryHandler(seller_htype_chosen, pattern="^flow_sell_htype_"), cancel_handler],
            SELLER_CONDITION: [
                CallbackQueryHandler(seller_condition_chosen, pattern="^flow_sell_cond_"),
                CallbackQueryHandler(seller_house_condition_chosen, pattern="^flow_sell_hcond_"),
                cancel_handler
            ],
            SELLER_HOUSE_CONDITION: [
                CallbackQueryHandler(seller_house_condition_chosen, pattern="^flow_sell_hcond_"),
                cancel_handler
            ],
            SELLER_FUEL: [CallbackQueryHandler(seller_fuel_chosen, pattern="^flow_sell_fuel_"), cancel_handler],
            SELLER_TRANSMISSION: [CallbackQueryHandler(seller_transmission_chosen, pattern="^flow_sell_trans_"), cancel_handler],
            SELLER_MILEAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_mileage), cancel_handler],
            SELLER_BEDROOMS: [CallbackQueryHandler(seller_bedrooms_chosen, pattern="^bed_"), cancel_handler],
            SELLER_PARKING: [CallbackQueryHandler(seller_parking_chosen, pattern="^park_"), cancel_handler],
            SELLER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_details), cancel_handler],
            SELLER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_price), cancel_handler],
            SELLER_NEGOTIABLE: [CallbackQueryHandler(seller_negotiable_chosen, pattern="^negotiable_"), cancel_handler],
            SELLER_URGENT: [CallbackQueryHandler(seller_urgent_chosen, pattern="^urgent_"), cancel_handler],
            SELLER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_phone), cancel_handler],
            SELLER_PHOTO: [
                MessageHandler(filters.PHOTO, seller_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, seller_photo),
                cancel_handler
            ],
        },
        fallbacks=[CommandHandler("start", start), cancel_handler],
        allow_reentry=True,
    )

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Broker Registration
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    broker_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^ðŸ“ áŠ¥áŠ•á‹° áŠ á‰…áˆ«á‰¢/á‹°áˆ‹áˆ‹ áˆ˜áˆ˜á‹áŒˆá‰¥$"), broker_reg_start)],
        states={
            BROKER_ROLE: [CallbackQueryHandler(broker_role_chosen, pattern="^role_"), cancel_handler],
            BROKER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_name), cancel_handler],
            BROKER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_phone), cancel_handler],
            BROKER_SUBCITY: [CallbackQueryHandler(broker_reg_subcity, pattern="^broker_sc_"), cancel_handler],
            BROKER_NID_PHOTO: [MessageHandler(filters.PHOTO, broker_reg_nid_photo), cancel_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_handler],
        allow_reentry=True,
    )

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Broker Offer Response (áŠ áˆˆáŠ)
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    broker_response_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(broker_have_item_click, pattern="^have_item_")],
        states={
            BROKER_OFFER_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_offer_text), cancel_handler],
            BROKER_OFFER_PHOTO: [
                MessageHandler(filters.PHOTO, broker_offer_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, broker_offer_photo),
                cancel_handler
            ],
        },
        fallbacks=[CommandHandler("start", start), cancel_handler],
        allow_reentry=True,
    )

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Register Handlers
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    app.add_handler(CommandHandler("start", start))
    app.add_handler(buyer_conv)
    app.add_handler(seller_conv)
    app.add_handler(broker_conv)
    app.add_handler(broker_response_conv)

    # Regular message handlers
    app.add_handler(MessageHandler(filters.Regex("^ðŸ“‹ á‹¨áˆáˆ‹áŒŠá‹Žá‰½ á‹áˆ­á‹áˆ­$"), view_requests))
    app.add_handler(MessageHandler(filters.Regex(r"^ðŸ›ï¸ á‹¨áŒˆá‰ á‹« á‰¦á‰³ \(á‹¨áˆšáˆ¸áŒ¡\)$"), view_public_marketplace))
    app.add_handler(MessageHandler(filters.Regex("^ðŸ‘¥ á‹¨á‹°áˆ‹áˆŽá‰½/áŠ á‰…áˆ«á‰¢á‹Žá‰½ áˆ›á‹áŒ«$"), view_brokers_directory))
    app.add_handler(MessageHandler(filters.Regex("^ðŸ“ž á‹µáŒ‹á$"), help_command))
    app.add_handler(MessageHandler(filters.Regex("^â¤ï¸ á‹¨á‰°á‹ˆá‹³áŒ†á‰½ á‹áˆ­á‹áˆ­$"), view_favorites))
    app.add_handler(MessageHandler(filters.Regex("^âš™ï¸ á‹¨áˆ›áˆ³á‹ˆá‰‚á‹« áˆáˆ­áŒ«$"), notification_prefs_start))
    app.add_handler(cancel_handler)

    # Callback query handlers
    app.add_handler(CallbackQueryHandler(go_home, pattern="^flow_home$"))
    app.add_handler(CallbackQueryHandler(admin_approval_callback, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(delete_request_callback, pattern=r"^delete_req_"))
    app.add_handler(CallbackQueryHandler(nohave_item_callback, pattern="^nohave_item_"))
    app.add_handler(CallbackQueryHandler(filter_brokers_by_subcity_callback, pattern="^dir_sc_"))
    app.add_handler(CallbackQueryHandler(toggle_favorite_callback, pattern="^fav_"))
    app.add_handler(CallbackQueryHandler(mark_sold_callback, pattern="^mark_sold_"))
    app.add_handler(CallbackQueryHandler(have_buyer_callback, pattern="^have_buyer_"))
    app.add_handler(CallbackQueryHandler(want_myself_callback, pattern="^want_myself_"))
    app.add_handler(CallbackQueryHandler(notification_prefs_callback, pattern="^notif_pref_"))
    app.add_handler(CallbackQueryHandler(view_detail_callback, pattern="^view_detail_"))

    logger.info("ðŸš€ Adika Marketplace Bot á‰ áˆµáŠ¬á‰µ á‰°áŒ€áˆáˆ¯áˆ...")
    app.run_polling()


if __name__ == "__main__":
    main()