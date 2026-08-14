# ==============================================================================
# ADIKA MARKETPLACE BOT - FULLY FIXED WITH MINI APP EXPLORER
# ==============================================================================

import logging
import os
import re
import asyncio
import threading
import json
import base64
from io import BytesIO
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
    raise RuntimeError("❌ BOT_TOKEN environment variable ውስጥ አልተገኘም።")

ADMIN_CHAT_ID_INT = int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID else 0
DB_FILE = "adika_marketplace.db"
ITEMS_PER_PAGE = 5

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

bot_app: Optional[Application] = None

# ==============================================================================
# 2. FLASK WEB SERVER & WEBAPP
# ==============================================================================

web_app = Flask(__name__)

# ==============================================================================
# EXPLORER HTML - MINI APP
# ==============================================================================

EXPLORER_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { background: #f3f4f6; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
        .tab-active { border-bottom: 3px solid #2563eb; color: #1e293b; font-weight: 600; }
        .tab-inactive { color: #64748b; }
        .card { background: white; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow: hidden; }
        .status-badge { display: inline-block; padding: 2px 10px; border-radius: 9999px; font-size: 11px; font-weight: 600; }
        .status-active { background: #dcfce7; color: #166534; }
        .status-closed { background: #fee2e2; color: #991b1b; }
        .filter-bar { background: white; border-bottom: 1px solid #e2e8f0; padding: 12px 16px; position: sticky; top: 0; z-index: 10; }
        .btn-primary { background: #2563eb; color: white; padding: 8px 16px; border-radius: 8px; font-weight: 500; border: none; cursor: pointer; }
        .btn-primary:active { transform: scale(0.96); }
        .btn-outline { background: transparent; border: 1px solid #e2e8f0; padding: 8px 16px; border-radius: 8px; cursor: pointer; }
        .btn-outline:active { transform: scale(0.96); }
        .action-btn { display: inline-flex; align-items: center; gap: 4px; padding: 6px 12px; border-radius: 6px; font-size: 13px; border: none; cursor: pointer; }
        .action-btn-call { background: #dcfce7; color: #166534; }
        .action-btn-telegram { background: #dbeafe; color: #1e40af; }
        .action-btn:active { transform: scale(0.96); }
        .tab-container { display: flex; gap: 0; background: white; border-bottom: 1px solid #e2e8f0; }
        .tab-item { padding: 12px 20px; cursor: pointer; font-size: 14px; border-bottom: 3px solid transparent; transition: all 0.2s; }
        .tab-item.active { border-bottom-color: #2563eb; color: #1e293b; font-weight: 600; }
        .tab-item.inactive { color: #64748b; }
        .tab-item:active { transform: scale(0.96); }
    </style>
</head>
<body>
    <div id="app">
        <div class="tab-container">
            <div class="tab-item active" data-tab="marketplace" onclick="switchTab('marketplace')">
                🛒 ገበያ
            </div>
            <div class="tab-item inactive" data-tab="requests" onclick="switchTab('requests')">
                📋 ፈላጊዎች
            </div>
        </div>

        <div class="filter-bar">
            <div class="flex flex-wrap gap-2 items-center">
                <select id="categoryFilter" class="border rounded px-3 py-1.5 text-sm bg-white">
                    <option value="">ሁሉም ምድብ</option>
                    <option value="መኪና">🚗 መኪና</option>
                    <option value="ቤት">🏠 ቤት</option>
                </select>
                <select id="dealFilter" class="border rounded px-3 py-1.5 text-sm bg-white">
                    <option value="">ሁሉም</option>
                    <option value="መሸጥ">ለሽያጭ</option>
                    <option value="መከራየት">ለኪራይ</option>
                </select>
                <button onclick="applyFilters()" class="btn-primary text-sm py-1.5">🔍 ፈልግ</button>
            </div>
        </div>

        <div id="content" class="p-4">
            <div id="loading" class="text-center py-8 text-gray-500">⏳ እየተጫነ...</div>
            <div id="listings" class="space-y-4"></div>
            <div id="pagination" class="flex justify-center gap-2 mt-4"></div>
        </div>
    </div>

    <script>
        let tg = window.Telegram.WebApp;
        tg.expand();
        tg.ready();

        let currentTab = 'marketplace';
        let currentPage = 0;
        let totalPages = 1;
        const limit = 5;

        function switchTab(tab) {
            currentTab = tab;
            currentPage = 0;
            document.querySelectorAll('.tab-item').forEach(el => {
                el.classList.toggle('active', el.dataset.tab === tab);
                el.classList.toggle('inactive', el.dataset.tab !== tab);
            });
            loadData();
        }

        function applyFilters() {
            currentPage = 0;
            loadData();
        }

        async function loadData() {
            const container = document.getElementById('listings');
            const loading = document.getElementById('loading');
            const pagination = document.getElementById('pagination');
            
            loading.classList.remove('hidden');
            container.innerHTML = '';
            pagination.innerHTML = '';

            const category = document.getElementById('categoryFilter').value;
            const dealType = document.getElementById('dealFilter').value;

            let url;
            if (currentTab === 'marketplace') {
                url = `/api/explorer/listings?limit=${limit}&offset=${currentPage * limit}`;
                if (category) url += `&category=${encodeURIComponent(category)}`;
                if (dealType) url += `&deal_type=${encodeURIComponent(dealType)}`;
            } else {
                url = `/api/explorer/requests?limit=${limit}&offset=${currentPage * limit}`;
                if (category) url += `&category=${encodeURIComponent(category)}`;
            }

            try {
                const res = await fetch(url);
                const data = await res.json();
                loading.classList.add('hidden');

                if (data.status === 'success' && data.data.length > 0) {
                    renderCards(data.data);
                    totalPages = Math.ceil(data.total / limit);
                    renderPagination();
                } else {
                    container.innerHTML = '<div class="text-center py-8 text-gray-500">📭 ምንም ውጤቶች የሉም</div>';
                }
            } catch (err) {
                loading.classList.add('hidden');
                container.innerHTML = '<div class="text-center py-8 text-red-500">❌ ስህተት ተከስቷል</div>';
            }
        }

        function renderCards(items) {
            const container = document.getElementById('listings');
            container.innerHTML = '';

            items.forEach(item => {
                const extraData = item.extra_data || {};
                const isCar = item.main_category === 'መኪና' || item.main_category === 'car' || item.main_category === 'CAR';
                const icon = isCar ? '🚗' : '🏠';
                const title = isCar ? 'VEHICLE' : 'PROPERTY';
                const reqType = (item.req_type || '').toUpperCase();
                const isBuy = reqType === 'BUY';
                const priceLabel = isBuy ? 'በጀት' : 'ዋጋ';
                const priceDisplay = isBuy ? (extraData.budget_range || item.price) : item.price;
                const statusBadge = item.status === 'sold' || item.status === 'closed' || item.status === 'deleted' 
                    ? '<span class="status-badge status-closed">🔴 Closed</span>' 
                    : '<span class="status-badge status-active">🟢 Active</span>';
                
                const actionLabel = item.action_type || '';
                const phone = item.phone || '-';
                const telegramUser = extraData.telegram_user || '';

                const card = document.createElement('div');
                card.className = 'card p-4';
                card.innerHTML = `
                    <div class="flex justify-between items-start">
                        <div>
                            <span class="font-bold text-lg">${icon} ${title}</span>
                            <span class="text-sm text-gray-500 ml-2">#ADK-${item.id}</span>
                            ${statusBadge}
                        </div>
                        <span class="text-sm text-gray-400">👀 ${item.view_count || 0}</span>
                    </div>
                    <div class="mt-1 text-gray-700 font-medium">${item.main_category}</div>
                    ${actionLabel ? `<div class="text-sm text-gray-600">${actionLabel}</div>` : ''}
                    <div class="mt-1 font-semibold text-blue-600">💰 ${priceLabel}: ${priceDisplay} ብር</div>
                    ${extraData.condition ? `<div class="text-sm text-gray-600">📊 ${extraData.condition}</div>` : ''}
                    ${extraData.bedrooms ? `<div class="text-sm text-gray-600">🛏️ ${extraData.bedrooms}</div>` : ''}
                    ${extraData.fuel_type ? `<div class="text-sm text-gray-600">⛽ ${extraData.fuel_type}</div>` : ''}
                    ${extraData.mileage ? `<div class="text-sm text-gray-600">🛣️ ${extraData.mileage} KM</div>` : ''}
                    ${item.description ? `<div class="text-sm text-gray-500 mt-1">📝 ${item.description.substring(0, 60)}...</div>` : ''}
                    <div class="mt-3 flex flex-wrap gap-2">
                        <a href="tel:${phone}" class="action-btn action-btn-call">📞 ደውል</a>
                        ${telegramUser ? `<a href="https://t.me/${telegramUser.replace('@', '')}" class="action-btn action-btn-telegram">💬 በቴሌግራም አውራ</a>` : ''}
                        ${!telegramUser && phone ? `<a href="https://t.me/${phone}" class="action-btn action-btn-telegram">💬 በቴሌግራም</a>` : ''}
                    </div>
                    <div class="mt-2 text-xs text-gray-400">📅 ${new Date(item.created_at).toLocaleDateString()}</div>
                `;
                container.appendChild(card);

                fetch(`/api/explorer/view/${item.id}`, { method: 'POST' });
            });
        }

        function renderPagination() {
            const pagination = document.getElementById('pagination');
            pagination.innerHTML = '';
            if (totalPages <= 1) return;

            if (currentPage > 0) {
                const btn = document.createElement('button');
                btn.className = 'btn-outline text-sm py-1 px-3';
                btn.textContent = '◀️ ቀዳሚ';
                btn.onclick = () => { currentPage--; loadData(); };
                pagination.appendChild(btn);
            }

            const info = document.createElement('span');
            info.className = 'text-sm text-gray-600 px-3 py-1';
            info.textContent = `${currentPage + 1} / ${totalPages}`;
            pagination.appendChild(info);

            if (currentPage < totalPages - 1) {
                const btn = document.createElement('button');
                btn.className = 'btn-outline text-sm py-1 px-3';
                btn.textContent = 'ቀጣይ ▶️';
                btn.onclick = () => { currentPage++; loadData(); };
                pagination.appendChild(btn);
            }
        }

        loadData();
    </script>
</body>
</html>
"""

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
       <h2 class="text-xl font-bold mb-4 text-center">ንብረት ለገበያ ያቅርቡ</h2>
       <form id="listingForm" class="space-y-4">
           <div>
               <label class="block text-sm font-medium text-gray-700 mb-1">📦 ዋና ምድብ</label>
               <select id="category" class="w-full p-2 border rounded focus:ring-2 focus:ring-blue-500">
                   <option value="መኪና">🚗 መኪና</option>
                   <option value="ቤት">🏠 ቤት</option>
               </select>
           </div>
           <div id="dynamicFilters"></div>
           <div>
               <label class="block text-sm font-medium text-gray-700 mb-1">💰 ዋጋ (በብር)</label>
               <input type="number" id="price" placeholder="ለምሳሌ፦ 2500000" class="w-full p-2 border rounded" required>
           </div>
           <div class="flex items-center gap-2">
               <input type="checkbox" id="negotiable" checked class="w-4 h-4 text-blue-600">
               <label for="negotiable" class="text-sm text-gray-700">💰 ዋጋው የሚደራደር ነው</label>
           </div>
           <div class="flex items-center gap-2 bg-red-50 p-3 rounded-lg border border-red-200">
               <input type="checkbox" id="urgentSale" class="w-4 h-4 text-red-600">
               <label for="urgentSale" class="text-sm font-medium text-red-700">⚡ አስቸኳይ ሽያጭ (Urgent Sale)</label>
           </div>
           <div>
               <label class="block text-sm font-medium text-gray-700 mb-1">📝 ዝርዝር መግለጫ</label>
               <textarea id="description" placeholder="የንብረቱን ሙሉ ዝርዝር መረጃ ያስገቡ..." class="w-full p-2 border rounded h-24" required></textarea>
           </div>
           <div>
               <label class="block text-sm font-medium text-gray-700 mb-1">📸 ፎቶዎች (እስከ 5)</label>
               <input type="file" id="photos" accept="image/*" multiple class="w-full p-2 border rounded text-sm">
               <p class="text-xs text-gray-500 mt-1">ፎቶዎች በራስ-ሰር ይጨመቃሉ • ከ1 በላይ መምረጥ ይችላሉ</p>
               <div id="photoPreviews" class="image-preview-container"></div>
           </div>
           <div>
               <label class="block text-sm font-medium text-gray-700 mb-1">📞 ስልክ ቁጥር</label>
               <input type="tel" id="phone" placeholder="0911223344" class="w-full p-2 border rounded" required>
           </div>
           <div>
               <label class="block text-sm font-medium text-gray-700 mb-1">📱 Telegram Username (አማራጭ)</label>
               <input type="text" id="telegramUser" placeholder="@username" class="w-full p-2 border rounded">
           </div>
           <div class="flex gap-3 pt-4">
               <button type="submit" id="submitBtn" class="flex-1 bg-blue-600 text-white p-3 rounded font-bold hover:bg-blue-700 transition">✅ አረጋግጥና ለጥፍ</button>
               <button type="button" id="cancelBtn" class="flex-1 bg-gray-400 text-white p-3 rounded font-bold hover:bg-gray-500 transition">❌ ሰርዝ</button>
           </div>
       </form>
       <p id="statusMsg" class="text-center mt-4 text-sm hidden"></p>
   </div>
   <script>
       let tg = window.Telegram.WebApp;
       tg.expand();
       tg.ready();
       const categorySelect = document.getElementById('category');
       const dynamicFiltersDiv = document.getElementById('dynamicFilters');
       const carFiltersHTML = `
           <div class="space-y-3 border-t pt-3">
               <div>
                   <label class="block text-sm font-medium text-gray-700 mb-1">⛽ የነዳጅ አይነት</label>
                   <select id="fuelType" class="w-full p-2 border rounded">
                       <option value="">-- ይምረጡ --</option>
                       <option value="ቤንዚን">⛽ ቤንዚን</option>
                       <option value="ናፍጣ">🛢️ ናፍጣ</option>
                       <option value="ኤሌክትሪክ">⚡ ኤሌክትሪክ</option>
                       <option value="ሀይብሪድ">🔋 ሀይብሪድ</option>
                   </select>
               </div>
               <div>
                   <label class="block text-sm font-medium text-gray-700 mb-1">⚙️ ማርሽ (Transmission)</label>
                   <select id="transmission" class="w-full p-2 border rounded">
                       <option value="">-- ይምረጡ --</option>
                       <option value="ማንዋል">🕹️ ማንዋል</option>
                       <option value="ኦቶማቲክ">🤖 ኦቶማቲክ</option>
                   </select>
               </div>
               <div>
                   <label class="block text-sm font-medium text-gray-700 mb-1">🛣️ የኪሎሜትር መጠን (KM)</label>
                   <input type="number" id="mileage" placeholder="ለምሳሌ፦ 50000" class="w-full p-2 border rounded">
               </div>
               <div>
                   <label class="block text-sm font-medium text-gray-700 mb-1">📊 ሁኔታ</label>
                   <select id="condition" class="w-full p-2 border rounded">
                       <option value="">-- ይምረጡ --</option>
                       <option value="አዲስ">🆕 አዲስ</option>
                       <option value="ያገለገለ">✅ ያገለገለ</option>
                       <option value="ጥገና የሚፈልግ">🔧 ጥገና የሚፈልግ</option>
                   </select>
               </div>
               <div>
                   <label class="block text-sm font-medium text-gray-700 mb-1">🚗 የመኪና አይነት/ሞዴል</label>
                   <select id="carType" class="w-full p-2 border rounded">
                       <option value="">-- ይምረጡ --</option>
                       <option value="የቤት መኪና">🚗 የቤት መኪና</option>
                       <option value="የሥራ መኪና">🚚 የሥራ መኪና</option>
                       <option value="ከባድ ተሽከርካሪ">🚜 ከባድ ተሽከርካሪ</option>
                   </select>
               </div>
           </div>
       `;
       const houseFiltersHTML = `
           <div class="space-y-3 border-t pt-3">
               <div>
                   <label class="block text-sm font-medium text-gray-700 mb-1">🛏️ የመኝታ ክፍል ብዛት</label>
                   <select id="bedrooms" class="w-full p-2 border rounded">
                       <option value="">-- ይምረጡ --</option>
                       <option value="1">1</option><option value="2">2</option><option value="3">3</option>
                       <option value="4">4</option><option value="5+">5+</option>
                   </select>
               </div>
               <div>
                   <label class="block text-sm font-medium text-gray-700 mb-1">🛁 የመታጠቢያ ክፍል ብዛት</label>
                   <select id="bathrooms" class="w-full p-2 border rounded">
                       <option value="">-- ይምረጡ --</option>
                       <option value="1">1</option><option value="2">2</option><option value="3">3</option>
                       <option value="4+">4+</option>
                   </select>
               </div>
               <div class="flex items-center gap-2">
                   <input type="checkbox" id="parking" class="w-4 h-4 text-blue-600">
                   <label for="parking" class="text-sm text-gray-700">🚗 ፓርኪንግ አለው</label>
               </div>
               <div>
                   <label class="block text-sm font-medium text-gray-700 mb-1">📊 ሁኔታ</label>
                   <select id="houseCondition" class="w-full p-2 border rounded">
                       <option value="">-- ይምረጡ --</option>
                       <option value="አዲስ">🆕 አዲስ</option>
                       <option value="ጥሩ">✅ ጥሩ</option>
                       <option value="እድሳት የሚፈልግ">🔧 እድሳት የሚፈልግ</option>
                   </select>
               </div>
               <div>
                   <label class="block text-sm font-medium text-gray-700 mb-1">🏠 የቤት አይነት</label>
                   <select id="houseType" class="w-full p-2 border rounded">
                       <option value="">-- ይምረጡ --</option>
                       <option value="ቪላ">🏡 ቪላ</option>
                       <option value="አፓርታማ">🏢 አፓርታማ</option>
                       <option value="ኮንዶሚኒየም">🏢 ኮንዶሚኒየም</option>
                       <option value="ሪል እስቴት">🏢 ሪል እስቴት</option>
                       <option value="መሬት">🏞️ መሬት/ቦታ</option>
                   </select>
               </div>
           </div>
       `;
       function updateFilters() {
           dynamicFiltersDiv.innerHTML = categorySelect.value === 'መኪና' ? carFiltersHTML : houseFiltersHTML;
       }
       categorySelect.addEventListener('change', updateFilters);
       updateFilters();
       const photoInput = document.getElementById('photos');
       const previewDiv = document.getElementById('photoPreviews');
       let compressedFiles = [];
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
                   removeBtn.innerHTML = '×';
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
           for (const file of newFiles) {
               if (compressedFiles.length >= 5) break;
               const compressed = await compressImage(file);
               compressedFiles.push(compressed);
           }
           photoInput.value = '';
           renderPreviews();
       });
       document.getElementById('cancelBtn').addEventListener('click', () => {
           if (confirm('እርግጠኛ ነዎት? ሁሉም ያስገቡት መረጃ ይጠፋል።')) {
               tg.close();
           }
       });
       document.getElementById('listingForm').onsubmit = async (e) => {
           e.preventDefault();
           const btn = document.getElementById('submitBtn');
           const status = document.getElementById('statusMsg');
           btn.disabled = true;
           btn.innerText = "እየተላከ ነው...";
           status.classList.add('hidden');
           const isCar = categorySelect.value === 'መኪና';
           const extraData = isCar ? {
               fuel_type: document.getElementById('fuelType')?.value || '',
               transmission: document.getElementById('transmission')?.value || '',
               mileage: document.getElementById('mileage')?.value || '',
               condition: document.getElementById('condition')?.value || '',
               car_type: document.getElementById('carType')?.value || '',
           } : {
               bedrooms: document.getElementById('bedrooms')?.value || '',
               bathrooms: document.getElementById('bathrooms')?.value || '',
               parking: document.getElementById('parking')?.checked ? 'አለ' : 'የለም',
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
                   status.innerHTML = `
                       <div class="text-green-600 font-medium">
                           ✅ ማስታወቂያዎ በስኬት ተመዝግቧል!<br>
                           🆔 ቁጥር፦ <b>#ADK-${result.req_id}</b><br><br>
                           📬 ለሁሉም ደላሎች ተልኳል።<br>
                           🗑️ ማስታወቂያውን ማጥፋት ከፈለጉ<br>
                           ከገበያ ቦታ ገብተው <b>አጥፋ</b> ቁልፍን ይጫኑ።
                       </div>
                   `;
                   status.classList.remove('hidden');
                   document.getElementById('listingForm').classList.add('hidden');
                   setTimeout(() => tg.close(), 4000);
               } else {
                   status.innerText = "❌ " + (result.message || "ስህተት ተከስቷል");
                   status.classList.remove('hidden');
                   status.classList.add('text-red-600');
                   btn.disabled = false;
                   btn.innerText = "✅ አረጋግጥና ለጥፍ";
               }
           } catch (err) {
               status.innerText = "❌ የኔትወርክ ስህተት። እንደገና ይሞክሩ።";
               status.classList.remove('hidden');
               status.classList.add('text-red-600');
               btn.disabled = false;
               btn.innerText = "✅ አረጋግጥና ለጥፍ";
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
       <h2 class="text-xl font-bold mb-4 text-center">የሚፈልጉትን ንብረት ይግለጹ</h2>
       <form id="buyerForm" class="space-y-4">
           <div>
               <label class="block text-sm font-medium text-gray-700 mb-1">📦 ምድብ</label>
               <select id="category" class="w-full p-2 border rounded">
                   <option value="መኪና">🚗 መኪና</option>
                   <option value="ቤት">🏠 ቤት</option>
               </select>
           </div>
           <div>
               <label class="block text-sm font-medium text-gray-700 mb-1">💰 የበጀት ክልል (በብር)</label>
               <div class="flex gap-2">
                   <input type="number" id="budgetMin" placeholder="ከ" class="w-1/2 p-2 border rounded">
                   <input type="number" id="budgetMax" placeholder="እስከ" class="w-1/2 p-2 border rounded">
               </div>
           </div>
           <div class="flex items-center gap-2 bg-blue-50 p-3 rounded-lg border border-blue-200">
               <input type="checkbox" id="createAlert" class="w-4 h-4 text-blue-600">
               <label for="createAlert" class="text-sm font-medium text-blue-700">🔔 ተመሳሳይ ንብረት ሲለቀቅ ይድረሰኝ</label>
           </div>
           <textarea id="details" placeholder="ዝርዝር ፍላጎትዎን ያስገቡ..." class="w-full p-2 border rounded h-24" required></textarea>
           <input type="tel" id="phone" placeholder="ስልክ ቁጥር" class="w-full p-2 border rounded" required>
           <input type="text" id="telegramUser" placeholder="Telegram Username (አማራጭ)" class="w-full p-2 border rounded">
           <div class="flex gap-3 pt-4">
               <button type="submit" id="submitBtn" class="flex-1 bg-green-600 text-white p-3 rounded font-bold hover:bg-green-700 transition">✅ ጥያቄውን ይላኩ</button>
               <button type="button" id="cancelBtn" class="flex-1 bg-gray-400 text-white p-3 rounded font-bold hover:bg-gray-500 transition">❌ ሰርዝ</button>
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
           btn.innerText = "እየተላከ ነው...";
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
                   status.innerHTML = `<span class="text-green-600">✅ ጥያቄዎ ተመዝግቧል!</span><br>🆔 ቁጥር፦ <b>#ADK-${result.req_id}</b>`;
                   status.classList.remove('hidden');
                   setTimeout(() => tg.close(), 2000);
               } else {
                   status.innerText = "❌ " + (result.message || "ስህተት ተከስቷል");
                   status.classList.remove('hidden');
                   status.classList.add('text-red-600');
                   btn.disabled = false;
                   btn.innerText = "✅ ጥያቄውን ይላኩ";
               }
           } catch (err) {
               status.innerText = "❌ የኔትወርክ ስህተት።";
               status.classList.remove('hidden');
               status.classList.add('text-red-600');
               btn.disabled = false;
               btn.innerText = "✅ ጥያቄውን ይላኩ";
           }
       };
   </script>
</body>
</html>
"""

@web_app.route('/')
def home():
   return "✅ Adika Marketplace Bot በስኬት እየሰራ ይገኛል!", 200

@web_app.route('/seller-form')
def webapp_seller_form():
   return render_template_string(SELLER_FORM_HTML)

@web_app.route('/buyer-form')
def webapp_buyer_form():
   return render_template_string(BUYER_FORM_HTML)

@web_app.route('/explorer')
def webapp_explorer():
   return render_template_string(EXPLORER_HTML)

# ==============================================================================
# EXPLORER API ENDPOINTS
# ==============================================================================

@web_app.route('/api/explorer/listings')
def api_explorer_listings():
    try:
        limit = int(request.args.get('limit', 5))
        offset = int(request.args.get('offset', 0))
        category = request.args.get('category', '')
        deal_type = request.args.get('deal_type', '')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        
        query = """
            SELECT 
                id, user_chat_id, user_name, req_type, main_category, 
                sub_category, action_type, property_type, description, 
                price, phone, photo_id, extra_data, status, created_at,
                COALESCE(view_count, 0) as view_count
            FROM listings 
            WHERE UPPER(req_type) = 'SELL'
              AND status != 'deleted'
        """
        params = []
        
        if category:
            query += f" AND main_category = {p}"
            params.append(category)
        
        if deal_type:
            query += f" AND action_type = {p}"
            params.append(deal_type)
        
        query += f" ORDER BY created_at DESC LIMIT {p} OFFSET {p}"
        params.extend([limit, offset])
        
        if DATABASE_URL:
            cursor.execute(query, params)
        else:
            query = query.replace('%s', '?')
            cursor.execute(query, params)
        
        rows = cursor.fetchall()
        
        listings = []
        for row in rows:
            item = dict(row) if isinstance(row, dict) else dict(zip([c[0] for c in cursor.description], row))
            if 'extra_data' in item and isinstance(item['extra_data'], str):
                try:
                    item['extra_data'] = json.loads(item['extra_data'])
                except:
                    item['extra_data'] = {}
            
            try:
                cursor.execute(f"SELECT photo_id FROM listing_photos WHERE listing_id = {p}", (item['id'],))
                photos = cursor.fetchall()
                item['photos'] = [dict(p)['photo_id'] if isinstance(p, dict) else p[0] for p in photos]
            except:
                item['photos'] = []
            
            listings.append(item)
        
        cursor.execute(f"SELECT COUNT(*) FROM listings WHERE UPPER(req_type) = 'SELL' AND status != 'deleted'")
        total = cursor.fetchone()[0]
        
        conn.close()
        
        return jsonify({
            'status': 'success',
            'data': listings,
            'total': total,
            'limit': limit,
            'offset': offset
        })
    except Exception as e:
        logger.error(f"API explorer listings error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@web_app.route('/api/explorer/requests')
def api_explorer_requests():
    try:
        limit = int(request.args.get('limit', 5))
        offset = int(request.args.get('offset', 0))
        category = request.args.get('category', '')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        
        query = """
            SELECT 
                id, user_chat_id, user_name, req_type, main_category, 
                sub_category, action_type, property_type, description, 
                price, phone, photo_id, extra_data, status, created_at,
                COALESCE(view_count, 0) as view_count
            FROM listings 
            WHERE UPPER(req_type) = 'BUY'
              AND status = 'pending'
        """
        params = []
        
        if category:
            query += f" AND main_category = {p}"
            params.append(category)
        
        query += f" ORDER BY created_at ASC LIMIT {p} OFFSET {p}"
        params.extend([limit, offset])
        
        if DATABASE_URL:
            cursor.execute(query, params)
        else:
            query = query.replace('%s', '?')
            cursor.execute(query, params)
        
        rows = cursor.fetchall()
        
        requests = []
        for row in rows:
            item = dict(row) if isinstance(row, dict) else dict(zip([c[0] for c in cursor.description], row))
            if 'extra_data' in item and isinstance(item['extra_data'], str):
                try:
                    item['extra_data'] = json.loads(item['extra_data'])
                except:
                    item['extra_data'] = {}
            requests.append(item)
        
        cursor.execute(f"SELECT COUNT(*) FROM listings WHERE UPPER(req_type) = 'BUY' AND status = 'pending'")
        total = cursor.fetchone()[0]
        
        conn.close()
        
        return jsonify({
            'status': 'success',
            'data': requests,
            'total': total,
            'limit': limit,
            'offset': offset
        })
    except Exception as e:
        logger.error(f"API explorer requests error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@web_app.route('/api/explorer/view/<int:listing_id>', methods=['POST'])
def api_increment_view(listing_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"UPDATE listings SET view_count = COALESCE(view_count, 0) + 1 WHERE id = {p}", (listing_id,))
        if not DATABASE_URL:
            conn.commit()
        conn.close()
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Increment view API error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

def _send_notification_safe(notification_text: str, req_id: int, buyer_id: int):
   if not bot_app:
       logger.warning("bot_app is None – cannot send notification")
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
               logger.info(f"✅ Notification sent for req_id={req_id}")
           except Exception as e:
               logger.error(f"❌ Notification thread error: {e}", exc_info=True)
       t = threading.Thread(target=run_in_thread, daemon=True)
       t.start()
   except Exception as e:
       logger.error(f"❌ Failed to start notification thread: {e}", exc_info=True)

@web_app.route('/api/submit-listing', methods=['POST'])
def submit_listing():
   try:
       data = request.json or {}
       user_id = data.get('user_id')
       category = data.get('category', 'መኪና')
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
       logger.info(f"📥 Seller WebApp data: {data}")
       if not user_id or user_id == "unknown":
           return jsonify({"status": "error", "message": "User ID አልተገኘም። Telegram ውስጥ ክፈት።"}), 400
       negotiable_text = "✅ የሚደራደር" if negotiable else "❌ የማይደራደር"
       urgent_text = "⚡ **አስቸኳይ ሽያጭ!** " if urgent_sale else ""
       full_desc = f"{urgent_text}"
       full_desc += f"💰 ዋጋ: {price} ብር ({negotiable_text})\n"
       if category == 'መኪና':
           if car_type: full_desc += f"🚗 አይነት: {car_type}\n"
           if fuel_type: full_desc += f"⛽ ነዳጅ: {fuel_type}\n"
           if transmission: full_desc += f"⚙️ ማርሽ: {transmission}\n"
           if mileage: full_desc += f"🛣️ ኪሎሜትር: {mileage} KM\n"
           if condition: full_desc += f"📊 ሁኔታ: {condition}\n"
       else:
           if house_type: full_desc += f"🏠 አይነት: {house_type}\n"
           if bedrooms: full_desc += f"🛏️ መኝታ: {bedrooms}\n"
           if bathrooms: full_desc += f"🛁 መታጠቢያ: {bathrooms}\n"
           if parking: full_desc += f"🚗 ፓርኪንግ: {parking}\n"
           if house_condition: full_desc += f"📊 ሁኔታ: {house_condition}\n"
       full_desc += f"📝 መግለጫ: {description}\n"
       full_desc += f"📞 ስልክ: {phone}\n"
       if telegram_user: full_desc += f"📱 Telegram: {telegram_user}\n"
       req_id = add_listing(
           user_chat_id=int(user_id) if str(user_id).isdigit() else 0,
           user_name="WebApp User",
           req_type="SELL",
           main_category=category,
           sub_category=car_type if category == 'መኪና' else house_type,
           action_type="መሸጥ",
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
           logger.info(f"✅ Seller listing saved ID={req_id}")
           notification_text = (
               f"🛍️ **አዲስ የሽያጭ ማስታወቂያ (#ADK-{req_id})**\n\n"
               f"{full_desc}"
           )
           _send_notification_safe(notification_text, req_id, int(user_id))
           return jsonify({"status": "success", "req_id": req_id})
       else:
           return jsonify({"status": "error", "message": "Database ውስጥ ማስቀመጥ አልተቻለም።"}), 500
   except Exception as e:
       logger.error(f"❌ submit_listing error: {e}", exc_info=True)
       return jsonify({"status": "error", "message": f"Server Error: {str(e)}"}), 500

@web_app.route('/api/submit-request', methods=['POST'])
def submit_request():
   try:
       data = request.json or {}
       user_id = data.get('user_id')
       category = data.get('category', 'መኪና')
       budget_min = data.get('budget_min', '')
       budget_max = data.get('budget_max', '')
       create_alert = data.get('create_alert', False)
       details = data.get('details', '')
       phone = data.get('phone', '')
       telegram_user = data.get('telegram_user', '')
       logger.info(f"📥 Buyer WebApp data: {data}")
       if not user_id or user_id == "unknown":
           return jsonify({"status": "error", "message": "User ID አልተገኘም። Telegram ውስጥ ክፈት።"}), 400
       budget_range = f"{budget_min} - {budget_max}" if budget_min and budget_max else (budget_min or budget_max or "ያልተገለጸ")
       full_desc = (
           f"💰 በጀት ክልል: {budget_range} ብር\n"
           f"📝 ዝርዝር: {details}\n"
           f"📞 ስልክ: {phone}\n"
       )
       if telegram_user: full_desc += f"📱 Telegram: {telegram_user}\n"
       req_id = add_listing(
           user_chat_id=int(user_id) if str(user_id).isdigit() else 0,
           user_name="WebApp User",
           req_type="BUY",
           main_category=category,
           sub_category="",
           action_type="መግዛት",
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
           logger.info(f"✅ Buyer request saved ID={req_id}")
           notification_text = (
               f"🔔 **አዲስ የ{category} ጥያቄ (#ADK-{req_id})**\n\n"
               f"{full_desc}"
           )
           _send_notification_safe(notification_text, req_id, int(user_id))
           if create_alert and str(user_id).isdigit():
               save_search_alert(int(user_id), category, budget_min, budget_max)
           return jsonify({"status": "success", "req_id": req_id})
       else:
           return jsonify({"status": "error", "message": "Database ውስጥ ማስቀመጥ አልተቻለም።"}), 500
   except Exception as e:
       logger.error(f"❌ submit_request error: {e}", exc_info=True)
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    view_count INTEGER DEFAULT 0
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    view_count INTEGER DEFAULT 0
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
                CREATE TABLE IF NOT EXISTS listing_photos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    listing_id INTEGER NOT NULL,
                    photo_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
        
        try:
            if DATABASE_URL:
                cursor.execute("ALTER TABLE listings ADD COLUMN IF NOT EXISTS view_count INTEGER DEFAULT 0;")
            else:
                try:
                    cursor.execute("ALTER TABLE listings ADD COLUMN view_count INTEGER DEFAULT 0;")
                except:
                    pass
            if not DATABASE_URL:
                conn.commit()
        except Exception as alter_err:
            logger.warning(f"ALTER TABLE warning: {alter_err}")
        
        logger.info("✅ Adika Database initialized successfully")
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}")
        if conn and not DATABASE_URL:
            conn.rollback()
    finally:
        if conn:
            conn.close()


# ==============================================================================
# 4. DATABASE OPERATIONS
# ==============================================================================

def add_listing(user_chat_id, user_name, req_type, main_category, sub_category,
                action_type, property_type, description, price=None, phone=None, 
                photo_id=None, extra_data=None, photos=None):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        if extra_data is None:
            extra_data = {}
        extra_json = json.dumps(extra_data, ensure_ascii=False) if not isinstance(extra_data, str) else extra_data
        user_chat_id = int(user_chat_id) if user_chat_id else 0
        user_name = str(user_name or "User")
        req_type = str(req_type or "BUY").upper()
        main_category = str(main_category or "መኪና")
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
        logger.info(f"📝 Inserting listing: user={user_chat_id}, type={req_type}, cat={main_category}")
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
        logger.info(f"✅ Listing inserted with ID: {req_id}")
        if photos and req_id:
            logger.info(f"📸 Saving {len(photos)} photos for listing {req_id}")
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
        logger.info(f"✅ Listing added successfully → #ADK-{req_id}")
        return req_id
    except Exception as e:
        logger.error(f"❌ Add listing error: {e}", exc_info=True)
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
        if 'extra_data' in result and isinstance(result['extra_data'], str):
            try:
                result['extra_data'] = json.loads(result['extra_data'])
            except:
                result['extra_data'] = {}
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

def get_listings_by_category_ordered(limit=ITEMS_PER_PAGE, offset=0, req_type=None, order="ASC"):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        order_sql = "ASC" if str(order).upper() == "ASC" else "DESC"
        if req_type:
            query = f"""
                SELECT * FROM listings 
                WHERE status = 'pending' AND UPPER(req_type) = UPPER({p})
                ORDER BY created_at {order_sql}
                LIMIT {p} OFFSET {p}
            """
            cursor.execute(query, (req_type, limit, offset))
        else:
            query = f"""
                SELECT * FROM listings 
                WHERE status = 'pending' 
                ORDER BY created_at {order_sql}
                LIMIT {p} OFFSET {p}
            """
            cursor.execute(query, (limit, offset))
        rows = cursor.fetchall()
        results = []
        for row in rows:
            item = dict(row) if isinstance(row, dict) else dict(zip([c[0] for c in cursor.description], row))
            if 'extra_data' in item and isinstance(item['extra_data'], str):
                try:
                    item['extra_data'] = json.loads(item['extra_data'])
                except:
                    item['extra_data'] = {}
            results.append(item)
        return results
    except Exception as e:
        logger.error(f"get_listings_by_category_ordered error: {e}")
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
            cursor.execute(
                f"SELECT COUNT(*) as cnt FROM listings WHERE status = 'pending' AND UPPER(req_type) = UPPER({p})",
                (req_type,)
            )
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
        logger.info(f"✅ Listing {req_id} status updated to {status}")
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

def get_public_marketplace_items(limit: int = ITEMS_PER_PAGE, offset: int = 0):
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return []
        cur = conn.cursor()
        p = get_placeholder()
        if DATABASE_URL:
            cur.execute("""
                SELECT * FROM listings 
                WHERE UPPER(req_type) = 'SELL'
                  AND status != 'deleted'
                ORDER BY created_at ASC NULLS LAST
                LIMIT %s OFFSET %s
            """, (limit, offset))
            rows = cur.fetchall()
            result = [dict(row) for row in rows]
        else:
            cur.execute("""
                SELECT * FROM listings 
                WHERE UPPER(req_type) = 'SELL'
                  AND status != 'deleted'
                ORDER BY created_at ASC
                LIMIT ? OFFSET ?
            """, (limit, offset))
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
            result = [dict(zip(columns, row)) for row in rows]
        for item in result:
            if 'extra_data' in item and isinstance(item['extra_data'], str):
                try:
                    item['extra_data'] = json.loads(item['extra_data'])
                except:
                    item['extra_data'] = {}
        return result
    except Exception as e:
        logger.error(f"get_public_marketplace_items error: {e}", exc_info=True)
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
        logger.info(f"✅ Broker registered: {broker_id}")
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
            if 'notification_prefs' in broker and isinstance(broker['notification_prefs'], str):
                try:
                    broker['notification_prefs'] = json.loads(broker['notification_prefs'])
                except:
                    broker['notification_prefs'] = {"car": True, "house": True, "enabled": True}
            results.append(broker)
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
        if sub_city and sub_city != "ሁሉም":
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
            cursor.execute("SELECT lastval()")
            row = cursor.fetchone()
            alert_id = row[0] if not isinstance(row, dict) else list(row.values())[0]
        else:
            alert_id = cursor.lastrowid
            conn.commit()
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


# ==============================================================================
# 5. CONSTANTS & KEYBOARDS
# ==============================================================================

EXPLORER_URL = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'adika-vrkk.onrender.com')}/explorer"

MAIN_KEYBOARD = [
   ["🔍 መግዛት / መከራየት", "📢 መሸጥ / ማከራየት"],
   ["🛍️ የገበያ ቦታ (የሚሸጡ)", "📋 የፈላጊዎች ዝርዝር"],
   ["👥 የደላሎች/አቅራቢዎች ማውጫ", "📝 እንደ አቅራቢ/ደላላ መመዝገብ"],
   ["📞 ድጋፍ", "⚙️ የማሳወቂያ ምርጫ"],
   ["🏠 ዋና ገጽ"]
]

SUB_CITIES = [
   "ቦሌ", "የካ", "አራዳ", "ልደታ",
   "ቂርቆስ", "አዲስ ከተማ", "ንፋስ ስልክ ላፍቶ",
   "ኮልፌ ቀራኒዮ", "አቃቂ ቃሊቲ", "ጉሌሌ", "ላምበርት/የካ"
]

CAR_SUB_CATEGORIES = ["🚗 የቤት መኪና", "🚚 የሥራ መኪና", "🚜 ከባድ ተሽከርካሪ/ማሽን"]
HOUSE_TYPES = ["🏡 ቪላ", "🏢 አፓርታማ", "🏢 ኮንዶሚኒየም", "🏢 ሪል እስቴት", "🏞️ መሬት/ቦታ"]
PROPERTY_TYPES = ["🏠 መኖሪያ ቤት", "🏢 የሥራ ቦታ / ንግድ"]
FUEL_TYPES = ["⛽ ቤንዚን", "🛢️ ናፍጣ", "⚡ ኤሌክትሪክ", "🔋 ሀይብሪድ"]
TRANSMISSION_TYPES = ["🕹️ ማንዋል", "🤖 ኦቶማቲክ"]
CONDITIONS = ["🆕 አዲስ", "✅ ያገለገለ", "🔧 ጥገና የሚፈልግ"]


# ==============================================================================
# 6. HELPER FUNCTIONS
# ==============================================================================

def validate_phone(phone: str) -> bool:
    if not phone:
        return False
    phone = phone.replace(' ', '').replace('-', '').replace('+', '')
    if re.match(r'^(09|07|01)\d{8}$', phone):
        return True
    if re.match(r'^(9|7)\d{8}$', phone):
        return True
    if re.match(r'^251(9|7)\d{8}$', phone):
        return True
    return False

def escape_markdown(text: str) -> str:
    if not text:
        return ""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', str(text))

def clean_description_md(desc: str, max_len: int = 60) -> str:
    if not desc:
        return ""
    junk = [
        'ዋጋ:', 'ስልክ:', 'አዲስ የሽያጭ', 'WebApp', 'አስቸኳይ ሽያጭ', 
        'መግለጫ:', '📝', '💰', '📞', '⚡', '📢', '🔄', '📦', 'NEW', 'እዱስ',
        '🔥 ለሽያጭ', '🔥 አሸጋጭ', 'የገበያ ቦታ', 'ለሽያጭ', 'ለኪራይ',
        'አይነት:', 'ምድብ:', 'ሁኔታ:', 'ነዳጅ:', 'ማርሽ:', 'ኪሎሜትር:',
        'መሸጥ', 'ማከራየት', 'መግዛት', 'መከራየት'
    ]
    clean = desc
    for j in junk:
        clean = clean.replace(j, '')
    clean = ' '.join(line.strip() for line in clean.splitlines() if line.strip())
    clean = ' '.join(clean.split())
    if len(clean) > max_len:
        clean = clean[:max_len] + "..."
    return escape_markdown(clean.strip())

def format_price_md(price: str) -> str:
    try:
        price_num = int(price.replace(',', '').replace(' ', ''))
        return f"{price_num:,}"
    except:
        return price

def get_status_badge_md(status: str) -> str:
    status_lower = status.lower()
    if status_lower in ('pending', 'active'):
        return "🟢 Active"
    elif status_lower in ('sold', 'closed', 'deleted'):
        return "🔴 Closed"
    else:
        return "⚪ Unknown"

def decode_base64_photo(photo_str: str):
    if not photo_str:
        return None
    if photo_str.startswith('data:image'):
        try:
            header, data = photo_str.split(',', 1)
            image_data = base64.b64decode(data)
            return BytesIO(image_data)
        except:
            return None
    return photo_str

def build_pagination_buttons(current_page: int, total_pages: int, prefix: str) -> InlineKeyboardMarkup:
    buttons = []
    if current_page > 0:
        buttons.append(InlineKeyboardButton("◀️ ቀዳሚ", callback_data=f"{prefix}_{current_page-1}"))
    if current_page < total_pages - 1:
        buttons.append(InlineKeyboardButton("ቀጣይ ▶️", callback_data=f"{prefix}_{current_page+1}"))
    if buttons:
        return InlineKeyboardMarkup([buttons])
    return None

def format_marketplace_card_md(item: dict) -> tuple:
    item_id = item.get('id', 'N/A')
    main_cat = item.get('main_category', '')
    price = item.get('price', '-')
    phone = item.get('phone', '-')
    desc = item.get('description', '')
    status = item.get('status', 'pending')
    
    extra_data = item.get('extra_data', {})
    if isinstance(extra_data, str):
        try:
            extra_data = json.loads(extra_data)
        except:
            extra_data = {}
    
    if main_cat in ["መኪና", "car", "CAR"]:
        title = "VEHICLE LISTING"
        icon = "🚗"
    else:
        title = "PROPERTY LISTING"
        icon = "🏠"
    
    badge = get_status_badge_md(status)
    
    action = item.get('action_type', '')
    if action in ["መሸጥ", "SELL"]:
        action_label = "ለሽያጭ"
    elif action in ["ማከራየት", "RENT"]:
        action_label = "ለኪራይ"
    else:
        action_label = ""
    
    negotiable = "የሚደራደር" if extra_data.get('negotiable', True) else "የማይደራደር"
    price_formatted = format_price_md(price)
    urgent = " ⚡ አስቸኳይ" if extra_data.get('urgent_sale') else ""
    
    details = []
    if main_cat in ["መኪና", "car", "CAR"]:
        if extra_data.get('condition'):
            details.append(f"├ ሁኔታ: {extra_data['condition']}")
        if extra_data.get('fuel_type'):
            details.append(f"├ ነዳጅ: {extra_data['fuel_type']}")
        if extra_data.get('transmission'):
            details.append(f"├ ማርሽ: {extra_data['transmission']}")
        if extra_data.get('mileage'):
            details.append(f"├ ኪሎሜትር: {extra_data['mileage']} KM")
        if extra_data.get('car_type'):
            details.append(f"├ አይነት: {extra_data['car_type']}")
    else:
        if extra_data.get('condition'):
            details.append(f"├ ሁኔታ: {extra_data['condition']}")
        if extra_data.get('bedrooms'):
            details.append(f"├ መኝታ: {extra_data['bedrooms']}")
        if extra_data.get('bathrooms'):
            details.append(f"├ መታጠቢያ: {extra_data['bathrooms']}")
        if extra_data.get('parking'):
            details.append(f"├ ፓርኪንግ: {extra_data['parking']}")
        if extra_data.get('house_type'):
            details.append(f"├ አይነት: {extra_data['house_type']}")
    
    clean_desc = clean_description_md(desc, 55)
    
    lines = [
        f"*{icon} {title}* • `#ADK-{item_id}`  {badge}",
        "",
        f"*{main_cat}*",
    ]
    
    if action_label:
        lines.append(f"*{action_label}*")
    
    price_line = f"*ዋጋ:* `{price_formatted}` ብር *({escape_markdown(negotiable)})*"
    if urgent:
        price_line += f" {urgent}"
    lines.append(price_line)
    lines.append("")
    
    if details:
        lines.append("*📋 ዝርዝር መረጃ*")
        lines.extend(details)
        lines.append("")
    
    if clean_desc:
        lines.append(f"*📝 ተጨማሪ:* {clean_desc}")
        lines.append("")
    
    lines.append(f"*📞 ስልክ:* `{escape_markdown(phone)}`")
    
    card_text = "\n".join(lines)
    
    owner_id = item.get('user_chat_id')
    current_user_id = item.get('_user_id', 0)
    
    keyboard = [
        [
            InlineKeyboardButton("🤝 ገዢ አለኝ", callback_data=f"have_buyer_{item_id}_{owner_id}"),
            InlineKeyboardButton("👤 ለራሴ", callback_data=f"want_myself_{item_id}")
        ]
    ]
    
    if current_user_id == owner_id or current_user_id == ADMIN_CHAT_ID_INT:
        keyboard.append([
            InlineKeyboardButton("✅ ተሸጧል", callback_data=f"mark_sold_{item_id}")
        ])
    
    return card_text, InlineKeyboardMarkup(keyboard)

def format_buyer_request_md(req: dict) -> tuple:
    req_id = req.get('id', 'N/A')
    main_cat = req.get('main_category', '')
    desc = req.get('description', '')
    phone = req.get('phone', '-')
    action_type = req.get('action_type', '')
    status = req.get('status', 'pending')
    
    extra_data = req.get('extra_data', {})
    if isinstance(extra_data, str):
        try:
            extra_data = json.loads(extra_data)
        except:
            extra_data = {}
    
    if main_cat in ["መኪና", "car", "CAR"]:
        title = "VEHICLE REQUEST"
        icon = "🔍"
    else:
        title = "PROPERTY REQUEST"
        icon = "🔍"
    
    badge = get_status_badge_md(status)
    clean_desc = clean_description_md(desc, 60)
    
    budget = extra_data.get('budget_range', '')
    if budget:
        try:
            if '-' in budget:
                parts = budget.split('-')
                if len(parts) == 2:
                    min_budget = parts[0].strip()
                    max_budget = parts[1].strip()
                    if min_budget.isdigit() and max_budget.isdigit():
                        budget = f"{int(min_budget):,} - {int(max_budget):,}"
        except:
            pass
    
    if action_type in ["መግዛት", "BUY"]:
        action_label = "መግዛት እፈልጋለሁ"
    elif action_type in ["መከራየት", "RENT"]:
        action_label = "መከራየት እፈልጋለሁ"
    else:
        action_label = action_type
    
    lines = [
        f"*{icon} {title}* • `#ADK-{req_id}`  {badge}",
        "",
        f"*{main_cat}*",
    ]
    
    if action_label:
        lines.append(f"*{action_label}*")
    
    if budget:
        lines.append(f"*በጀት:* `{budget}` ብር")
    
    if clean_desc:
        lines.append("")
        lines.append(f"*📝 ዝርዝር:* {clean_desc}")
    
    lines.append("")
    lines.append(f"*📞 ስልክ:* `{escape_markdown(phone)}`")
    
    card_text = "\n".join(lines)
    
    buyer_id = req.get('user_chat_id')
    keyboard = [
        [
            InlineKeyboardButton("✅ አለኝ", callback_data=f"have_item_{req_id}_{buyer_id}"),
            InlineKeyboardButton("⏭️ ይለፈኝ", callback_data=f"nohave_item_{req_id}")
        ]
    ]
    
    return card_text, InlineKeyboardMarkup(keyboard)

def format_broker_profile(b: dict) -> str:
    stars = "⭐" * int(float(b.get('rating', 5)))
    return (
        f"╭────────────────────╮\n"
        f"│  👤  **ደላላ**\n"
        f"╰────────────────────╯\n\n"
        f"**ስም:** {b.get('full_name')}\n"
        f"**ሚና:** {b.get('role_type')}\n"
        f"**ክፍለ ከተማ:** {b.get('sub_city')}\n"
        f"**ስልክ:** `{b.get('phone')}`\n"
        f"**ደረጃ:** {b.get('rating', 5.0)}/5.0 {stars}\n"
        f"──────────────────────"
    )

def build_request_keyboard(req_id: int, user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ አለኝ", callback_data=f"have_item_{req_id}_{user_id}"),
            InlineKeyboardButton("⏭️ ይለፈኝ", callback_data=f"nohave_item_{req_id}")
        ]
    ])

def build_seller_card_keyboard(item_id: int, owner_id: int, current_user_id: int, phone: str = "") -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("🤝 ገዢ አለኝ", callback_data=f"have_buyer_{item_id}_{owner_id}"),
            InlineKeyboardButton("👤 ለራሴ ነው", callback_data=f"want_myself_{item_id}")
        ]
    ]
    if current_user_id == owner_id or current_user_id == ADMIN_CHAT_ID_INT:
        keyboard.append([
            InlineKeyboardButton("✅ ተሸጧል", callback_data=f"mark_sold_{item_id}")
        ])
    return InlineKeyboardMarkup(keyboard)

async def notify_brokers(bot, message_text: str, req_id: int, buyer_id: int, photos: list = None):
    try:
        approved_brokers = get_approved_brokers()
        if not approved_brokers:
            logger.warning("No approved brokers found")
            return
        
        listing = get_listing_by_id(req_id)
        if not listing:
            logger.error(f"Listing {req_id} not found")
            return
        
        main_category = listing.get('main_category', '')
        req_type = str(listing.get('req_type', 'BUY')).upper()
        owner_id = listing.get('user_chat_id')
        sent_count = 0
        
        photo_io = None
        if photos and len(photos) > 0:
            photo_io = decode_base64_photo(photos[0])
        
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
                if main_category in ['መኪና', 'car', 'CAR'] and not prefs.get('car', True):
                    continue
                if main_category in ['ቤት', 'house'] and not prefs.get('house', True):
                    continue
                
                if req_type == "SELL":
                    kbd = [[
                        InlineKeyboardButton("🤝 ገዢ አለኝ", callback_data=f"have_buyer_{req_id}_{owner_id}"),
                        InlineKeyboardButton("👤 ለራሴ", callback_data=f"want_myself_{req_id}")
                    ]]
                else:
                    kbd = [[
                        InlineKeyboardButton("✅ አለኝ", callback_data=f"have_item_{req_id}_{buyer_id}"),
                        InlineKeyboardButton("⏭️ ይለፈኝ", callback_data=f"nohave_item_{req_id}")
                    ]]
                
                if photo_io:
                    try:
                        await bot.send_photo(
                            chat_id=b_id,
                            photo=photo_io,
                            caption=message_text,
                            parse_mode="HTML",
                            reply_markup=InlineKeyboardMarkup(kbd)
                        )
                    except Exception as e:
                        logger.error(f"Failed to send photo to broker {b_id}: {e}")
                        await bot.send_message(
                            chat_id=b_id,
                            text=message_text,
                            parse_mode="HTML",
                            reply_markup=InlineKeyboardMarkup(kbd)
                        )
                else:
                    await bot.send_message(
                        chat_id=b_id,
                        text=message_text,
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(kbd)
                    )
                sent_count += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.error(f"Notify broker error: {e}")
        
        logger.info(f"✅ Sent to {sent_count} brokers for #ADK-{req_id}")
    except Exception as e:
        logger.error(f"notify_brokers error: {e}", exc_info=True)


# ==============================================================================
# 7. CONVERSATION STATES
# ==============================================================================

(
   BUYER_MAIN, BUYER_ACTION, BUYER_SUB, BUYER_PROPERTY, BUYER_HTYPE,
   BUYER_DETAILS, BUYER_PHONE, BUYER_TELEGRAM_USER, BUYER_BUDGET_RANGE, 
   BUYER_ALERT, BUYER_ALERT_CHOICE,
   SELLER_MAIN, SELLER_ACTION, SELLER_SUB, SELLER_PROPERTY, SELLER_HTYPE,
   SELLER_DETAILS, SELLER_PRICE, SELLER_NEGOTIABLE, SELLER_URGENT, 
   SELLER_CONDITION, SELLER_FUEL, SELLER_TRANSMISSION, SELLER_MILEAGE,
   SELLER_BEDROOMS, SELLER_PARKING, SELLER_PHONE, SELLER_TELEGRAM_USER,
   SELLER_PHOTO, SELLER_HOUSE_CONDITION,
   BROKER_ROLE, BROKER_NAME, BROKER_PHONE, BROKER_SUBCITY, BROKER_NID_PHOTO,
   BROKER_OFFER_TEXT, BROKER_OFFER_PHOTO,
   NOTIFICATION_PREFS
) = range(38)


# ==============================================================================
# 8. START & HOME HANDLERS
# ==============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
   context.user_data.clear()
   welcome_text = (
       "👋 **እንኳን ወደ Adika Marketplace በደህና መጡ!**\n\n"
       "የሀገሪቱ ታላቁ የመኪና፣ የቤት እና የንብረት ገበያ ማዕከል።\n\n"
       "እባክዎን ከታች ካሉት አማራጮች አንዱን ይምረጡ፦"
   )
   await update.message.reply_text(
       welcome_text,
       parse_mode="Markdown",
       reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
   )
   return ConversationHandler.END

async def go_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
   context.user_data.clear()
   welcome_text = "👋 **ወደ ዋና ገጽ ተመልሰዋል!**\n\nእባክዎን አማራጭ ይምረጡ፦"
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

async def explorer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Web App Explorer መክፈቻ - በ Inline Keyboard"""
    web_app_url = EXPLORER_URL
    
    keyboard = [
        [InlineKeyboardButton("🛍️ ማሰሻ (የሚኒ አፕ)", web_app=WebAppInfo(url=web_app_url))],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    
    await update.message.reply_text(
        "🛍️ **Adika Marketplace - ማሰሻ**\n\n"
        "ከታች ያለውን ቁልፍ በመጫን የገበያ ቦታን እና የፈላጊዎችን ዝርዝር በሚኒ አፕ ውስጥ ይመልከቱ።\n\n"
        "💡 *ምን ማድረግ ይችላሉ?*\n"
        "• 🛒 ለሽያጭ የቀረቡ ንብረቶችን ይመልከቱ\n"
        "• 📋 የፈላጊዎችን ጥያቄዎች ይመልከቱ\n"
        "• 🔍 በምድብ እና በድርጊት ይፈልጉ\n"
        "• 📞 በአንድ ጠቅታ ይደውሉ\n"
        "• 💬 በቴሌግራም ያነጋግሩ",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


# ==============================================================================
# 9. BUYER FLOW
# ==============================================================================

async def buyer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
   context.user_data.clear()
   context.user_data['req_type'] = 'BUY'
   web_app_url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'adika-vrkk.onrender.com')}/buyer-form"
   keyboard = [
       [InlineKeyboardButton("🌐 በፎርም በፍጥነት ለመሙላት (WebApp)", web_app=WebAppInfo(url=web_app_url))],
       [InlineKeyboardButton("🚗 መኪና", callback_data="flow_buy_cat_car")],
       [InlineKeyboardButton("🏠 ቤት / ቦታ", callback_data="flow_buy_cat_house")],
       [InlineKeyboardButton("🏢 የሥራ ቦታ / ንግድ", callback_data="flow_buy_cat_commercial")],
       [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
   ]
   await update.message.reply_text(
       "🔍 **የሚፈልጉትን ምድብ ይምረጡ፦**\n\n"
       "💡 *በአንድ ገጽ ላይ በቀላሉ ለመሙላት 'በፎርም በፍጥነት ለመሙላት' የሚለውን አዝራር መጠቀም ይችላሉ።*",
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
       keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
       await query.edit_message_text(
           "🚗 **የመኪና አይነት/ሞዴል ይምረጡ፦**",
           reply_markup=InlineKeyboardMarkup(keyboard),
           parse_mode="Markdown"
       )
       return BUYER_SUB
   else:
       keyboard = [
           [InlineKeyboardButton("🛍️ መግዛት", callback_data="flow_buy_action_buy")],
           [InlineKeyboardButton("🔑 መከራየት", callback_data="flow_buy_action_rent")],
           [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
       ]
       await query.edit_message_text(
           "❓ **የሚፈልጉትን የድርጊት አይነት ይምረጡ፦**",
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
       [InlineKeyboardButton("🛍️ መግዛት", callback_data="flow_buy_action_buy")],
       [InlineKeyboardButton("🔑 መከራየት", callback_data="flow_buy_action_rent")],
       [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
   ]
   await query.edit_message_text(
       f"✅ {sub}\n\n❓ **የሚፈልጉትን የድርጊት አይነት ይምረጡ፦**",
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
   context.user_data['action_type'] = "መግዛት" if action == "buy" else "መከራየት"
   await query.edit_message_text(
       "💰 **የበጀት ክልልዎን ያስገቡ፦**\n\n"
       "💡 *ምሳሌ፦* `500000-1000000` (ከ 500ሺህ እስከ 1 ሚሊዮን ብር)\n"
       "ወይም አንድ ቁጥር ብቻ ያስገቡ (ለምሳሌ 2000000)",
       parse_mode="Markdown"
   )
   return BUYER_BUDGET_RANGE

async def buyer_budget_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
   if update.message.text == "🏠 ዋና ገጽ":
       return await go_home(update, context)
   context.user_data['budget_range'] = update.message.text.strip()
   keyboard = [
       [InlineKeyboardButton("✅ አዎ - ማሳወቂያ ደርሶኝ", callback_data="alert_yes")],
       [InlineKeyboardButton("❌ አይ - አያስፈልገኝም", callback_data="alert_no")],
       [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
   ]
   await update.message.reply_text(
       "🔔 **ተመሳሳይ ንብረት ሲለቀቅ ማሳወቂያ እንዲደርስዎ ይፈልጋሉ?**",
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
           "✍️ **የሚፈልጉትን መኪና ዝርዝር መረጃ ያስገቡ፦**\n\n💡 *ምሳሌ፦* ቶዮታ ቪትዝ 2020፣ ነጭ ቀለም፣ ኦቶማቲክ",
           parse_mode="Markdown"
       )
       return BUYER_DETAILS
   else:
       keyboard = [[InlineKeyboardButton(ptype, callback_data=f"flow_buy_prop_{ptype}")] for ptype in PROPERTY_TYPES]
       keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
       await query.edit_message_text(
           "🏠 **የንብረት አይነት ይምረጡ፦**",
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
   keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
   await query.edit_message_text(
       "🏠 **የቤቱ አይነት ይምረጡ፦**",
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
       f"🏠 **የቤቱ አይነት፦ {htype}**\n\n✍️ **የሚፈልጉትን ቤት/ቦታ ዝርዝር መረጃ ያስገቡ፦**\n\n💡 *ምሳሌ፦* ቦሌ 2 መኝታ፣ ፓርኪንግ ያለው",
       parse_mode="Markdown"
   )
   return BUYER_DETAILS

async def buyer_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
   if update.message.text == "🏠 ዋና ገጽ":
       return await go_home(update, context)
   context.user_data['description'] = update.message.text
   await update.message.reply_text(
       "📞 **ስልክ ቁጥርዎን ያስገቡ፦**\n\n"
       "📱 **Telegram Username (አማራጭ)** ማከል ከፈለጉ ከስልኩ ጋር ያስገቡ።\n"
       "💡 *ለምሳሌ፦* `0911223344 @Abebe`",
       parse_mode="Markdown",
       reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
   )
   return BUYER_PHONE

async def buyer_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
   if update.message.text == "🏠 ዋና ገጽ":
       return await go_home(update, context)
   text = update.message.text.strip()
   telegram_user = ""
   phone = text
   username_match = re.search(r'@\w+', text)
   if username_match:
       telegram_user = username_match.group()
       phone = text.replace(telegram_user, '').strip()
   if not validate_phone(phone):
       await update.message.reply_text("❌ ትክክለኛ የስልክ ቁጥር ያስገቡ። (ለምሳሌ፦ 0911223344 ወይም 0911223344 @Abebe)")
       return BUYER_PHONE
   context.user_data["phone"] = phone
   context.user_data["telegram_user"] = telegram_user
   user = update.effective_user
   user_data = context.user_data
   desc = user_data.get('description', '')
   budget = user_data.get('budget_range', '')
   main_category = user_data.get('main_category', '')
   if user_data.get('property_subtype'):
       desc = f"🏠 {user_data.get('property_subtype')}\n{desc}"
   try:
       req_id = add_listing(
           user_chat_id=user.id,
           user_name=user.first_name or "User",
           req_type="BUY",
           main_category=main_category,
           sub_category=user_data.get('sub_category', ''),
           action_type=user_data.get('action_type', 'መግዛት'),
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
               f"✅ **ጥያቄዎ በስኬት ተመዝግቧል!** 🎉\n\n"
               f"🆔 **የጥያቄ ቁጥር:** #ADK-{req_id}\n"
               f"📌 **ምድብ:** {main_category}\n"
               f"📞 **ስልክ:** {phone}\n"
               + (f"📱 **Telegram:** {telegram_user}\n" if telegram_user else "") +
               f"\nአቅራቢዎች ወይም ደላሎች ጥያቄዎን አይተው መልስ ይሰጡዎታል።",
               reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
               parse_mode="Markdown",
           )
           notification_text = format_marketplace_card_md({
               'id': req_id,
               'main_category': main_category,
               'sub_category': user_data.get('sub_category', ''),
               'action_type': user_data.get('action_type', 'መግዛት'),
               'req_type': 'BUY',
               'description': desc,
               'price': budget,
               'phone': phone,
               'extra_data': {
                   'budget_range': budget,
                   'telegram_user': telegram_user
               }
           })[0]
           await notify_brokers(context.bot, notification_text, req_id, user.id)
       else:
           await update.message.reply_text(
               "❌ **መረጃውን መመዝገብ አልተቻለም።**",
               reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
               parse_mode="Markdown"
           )
   except Exception as e:
       logger.error(f"❌ Buyer save error: {e}", exc_info=True)
       await update.message.reply_text(
           "❌ **ስህተት ተከስቷል።** እባክዎ እንደገና ይሞክሩ።",
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
       [InlineKeyboardButton("🌐 በፎርም በፍጥነት ለመሙላት (WebApp)", web_app=WebAppInfo(url=web_app_url))],
       [InlineKeyboardButton("🚗 መኪና", callback_data="flow_sell_cat_car")],
       [InlineKeyboardButton("🏠 ቤት / ቦታ", callback_data="flow_sell_cat_house")],
       [InlineKeyboardButton("🏢 የሥራ ቦታ / ንግድ", callback_data="flow_sell_cat_commercial")],
       [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
   ]
   await update.message.reply_text(
       "📢 **የሚሸጡትን ወይም የሚያከራዩትን ምድብ ይምረጡ፦**\n\n"
       "💡 *በአንድ ገጽ ላይ በቀላሉ ለመሙላት 'በፎርም በፍጥነት ለመሙላት' የሚለውን አዝራር መጠቀም ይችላሉ።*",
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
       keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
       await query.edit_message_text(
           "🚗 **የመኪና አይነት/ሞዴል ይምረጡ፦**",
           reply_markup=InlineKeyboardMarkup(keyboard),
           parse_mode="Markdown"
       )
       return SELLER_SUB
   else:
       keyboard = [
           [InlineKeyboardButton("🛍️ መሸጥ", callback_data="flow_sell_action_sell")],
           [InlineKeyboardButton("🔑 ማከራየት", callback_data="flow_sell_action_rent")],
           [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
       ]
       await query.edit_message_text(
           "❓ **የድርጊት አይነት ይምረጡ፦**",
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
       [InlineKeyboardButton("🛍️ መሸጥ", callback_data="flow_sell_action_sell")],
       [InlineKeyboardButton("🔑 ማከራየት", callback_data="flow_sell_action_rent")],
       [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
   ]
   await query.edit_message_text(
       f"✅ {sub}\n\n❓ **የድርጊት አይነት ይምረጡ፦**",
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
   context.user_data['action_type'] = "መሸጥ" if action == "sell" else "ማከራየት"
   
   if context.user_data.get('main_category') == "car":
       keyboard = [[InlineKeyboardButton(cond, callback_data=f"flow_sell_cond_{cond}")] for cond in CONDITIONS]
       keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
       await query.edit_message_text(
           "📊 **የመኪናውን ሁኔታ ይምረጡ፦**",
           reply_markup=InlineKeyboardMarkup(keyboard),
           parse_mode="Markdown"
       )
       return SELLER_CONDITION
   else:
       keyboard = [[InlineKeyboardButton(ptype, callback_data=f"flow_sell_prop_{ptype}")] for ptype in PROPERTY_TYPES]
       keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
       await query.edit_message_text(
           "🏠 **የንብረት አይነት ይምረጡ፦**",
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
   keyboard = [[InlineKeyboardButton(ftype, callback_data=f"flow_sell_fuel_{ftype}")] for ftype in FUEL_TYPES]
   keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
   await query.edit_message_text(
       f"✅ **ሁኔታ:** {cond}\n\n⛽ **የነዳጅ አይነት ይምረጡ፦**",
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
   keyboard = [[InlineKeyboardButton(ttype, callback_data=f"flow_sell_trans_{ttype}")] for ttype in TRANSMISSION_TYPES]
   keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
   await query.edit_message_text(
       f"⛽ **ነዳጅ:** {fuel}\n\n⚙️ **የማርሽ አይነት ይምረጡ፦**",
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
       f"⚙️ **ማርሽ:** {trans}\n\n🛣️ **የኪሎሜትር መጠን ያስገቡ (KM)፦**\n\n💡 *ለምሳሌ፦* 50000",
       parse_mode="Markdown"
   )
   return SELLER_MILEAGE

async def seller_mileage(update: Update, context: ContextTypes.DEFAULT_TYPE):
   if update.message.text == "🏠 ዋና ገጽ":
       return await go_home(update, context)
   if not update.message.text.isdigit():
       await update.message.reply_text("❌ እባክዎ ቁጥር ብቻ ያስገቡ።")
       return SELLER_MILEAGE
   context.user_data['mileage'] = update.message.text
   await update.message.reply_text(
       "✍️ **የመኪናውን ዝርዝር መረጃ ያስገቡ፦**\n\n💡 *ምሳሌ፦* ቶዮታ ቪትዝ 2020፣ ነጭ፣ አዲስ ጎማ፣ አክሲደንት ያልገጠመው",
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
   keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
   await query.edit_message_text(
       "🏠 **የቤቱ አይነት ይምረጡ፦**",
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
   
   conditions = ["🆕 አዲስ", "✅ ጥሩ", "🔧 እድሳት የሚፈልግ"]
   keyboard = [[InlineKeyboardButton(cond, callback_data=f"flow_sell_hcond_{cond}")] for cond in conditions]
   keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
   await query.edit_message_text(
       f"🏠 **የቤቱ አይነት፦** {htype}\n\n📊 **የቤቱን ሁኔታ ይምረጡ፦**",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return SELLER_HOUSE_CONDITION

async def seller_house_condition_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)
   await query.answer()
   cond = query.data.replace("flow_sell_hcond_", "")
   context.user_data['condition'] = cond
   
   keyboard = [
       [InlineKeyboardButton("1", callback_data="bed_1"), InlineKeyboardButton("2", callback_data="bed_2")],
       [InlineKeyboardButton("3", callback_data="bed_3"), InlineKeyboardButton("4", callback_data="bed_4")],
       [InlineKeyboardButton("5+", callback_data="bed_5+")],
       [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
   ]
   await query.edit_message_text(
       f"📊 **ሁኔታ:** {cond}\n\n🛏️ **የመኝታ ክፍል ብዛት ይምረጡ፦**",
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
   keyboard = [
       [InlineKeyboardButton("🚗 አለ", callback_data="park_yes")],
       [InlineKeyboardButton("❌ የለም", callback_data="park_no")],
       [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
   ]
   await query.edit_message_text(
       f"🛏️ **መኝታ:** {beds}\n\n🚗 **ፓርኪንግ አለው?**",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return SELLER_PARKING

async def seller_parking_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)
   await query.answer()
   parking = "አለ" if query.data == "park_yes" else "የለም"
   context.user_data['parking'] = parking
   await query.edit_message_text(
       f"🚗 **ፓርኪንግ:** {parking}\n\n✍️ **የቤቱን/ቦታውን ዝርዝር መረጃ ያስገቡ፦**\n💡 *ምሳሌ፦* ቦሌ አትላስ አካባቢ 3 መኝታ ቤት፣ ዘመናዊ ኩሽና",
       parse_mode="Markdown"
   )
   return SELLER_DETAILS

async def seller_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
   if update.message.text == "🏠 ዋና ገጽ":
       return await go_home(update, context)
   context.user_data['description'] = update.message.text
   await update.message.reply_text(
       "💰 **የሚሸጡበትን/ሚያከራዩበትን ዋጋ ያስገቡ፦**",
       reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True),
       parse_mode="Markdown"
   )
   return SELLER_PRICE

async def seller_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
   if update.message.text == "🏠 ዋና ገጽ":
       return await go_home(update, context)
   if not validate_price(update.message.text):
       await update.message.reply_text("❌ እባክዎ ቁጥር ብቻ ያስገቡ።")
       return SELLER_PRICE
   context.user_data['price'] = update.message.text
   keyboard = [
       [InlineKeyboardButton("✅ አዎ - የሚደራደር", callback_data="negotiable_yes")],
       [InlineKeyboardButton("❌ አይ - የማይደራደር", callback_data="negotiable_no")],
       [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
   ]
   await update.message.reply_text(
       "💰 **ዋጋው የሚደራደር ነው?**",
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
   keyboard = [
       [InlineKeyboardButton("⚡ አዎ - አስቸኳይ ነው", callback_data="urgent_yes")],
       [InlineKeyboardButton("❌ አይ - አስቸኳይ አይደለም", callback_data="urgent_no")],
       [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
   ]
   await query.edit_message_text(
       "⚡ **ይህ አስቸኳይ ሽያጭ ነው?**",
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
       "📞 **የስልክ ቁጥርዎን ያስገቡ፦**",
       parse_mode="Markdown"
   )
   return SELLER_PHONE

async def seller_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
   if update.message.text == "🏠 ዋና ገጽ":
       return await go_home(update, context)
   text = update.message.text.strip()
   telegram_user = ""
   phone = text
   username_match = re.search(r'@\w+', text)
   if username_match:
       telegram_user = username_match.group()
       phone = text.replace(telegram_user, '').strip()
   if not validate_phone(phone):
       await update.message.reply_text("❌ ትክክለኛ የስልክ ቁጥር ያስገቡ። (ለምሳሌ፦ 0911223344 ወይም 0911223344 @Abebe)")
       return SELLER_PHONE
   context.user_data['phone'] = phone
   context.user_data['telegram_user'] = telegram_user
   await update.message.reply_text(
       "📸 **የንብረቱን ፎቶ ይላኩ (ወይም 'ዝለል' የሚለውን ይጻፉ)፦**\n\n"
       "💡 *እስከ 5 ፎቶዎች መላክ ይችላሉ። ሲጨርሱ 'ጨረስኩ' ብለው ይጻፉ።*",
       parse_mode="Markdown",
       reply_markup=ReplyKeyboardMarkup([["ዝለል"], ["ጨረስኩ"], ["🏠 ዋና ገጽ"]], resize_keyboard=True)
   )
   return SELLER_PHOTO

async def seller_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
   if update.message.text == "🏠 ዋና ገጽ":
       return await go_home(update, context)
   if update.message.text and update.message.text.lower() in ['ዝለል', 'ጨረስኩ', 'ቀጥል']:
       return await save_seller_listing(update, context)
   if update.message.photo:
       if 'photos' not in context.user_data:
           context.user_data['photos'] = []
       if len(context.user_data['photos']) < 5:
           context.user_data['photos'].append(update.message.photo[-1].file_id)
           count = len(context.user_data['photos'])
           await update.message.reply_text(
               f"📸 **ፎቶ {count}/5 ተቀብያለሁ!**\n\n"
               f"ተጨማሪ ፎቶ ይላኩ ወይም ለማቆም 'ጨረስኩ' ብለው ይጻፉ።",
               parse_mode="Markdown"
           )
       else:
           await update.message.reply_text(
               "⚠️ ከፍተኛው 5 ፎቶ ነው። 'ጨረስኩ' ብለው ይጻፉ።",
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
    is_car = user_data.get('main_category') == "car"
    negotiable = user_data.get('negotiable', True)
    urgent_sale = user_data.get('urgent_sale', False)
    
    price = user_data.get('price', '')
    phone = user_data.get('phone', '')
    
    clean_description_text = clean_description_md(description, 100)
    
    extra_data = {
        'negotiable': negotiable,
        'urgent_sale': urgent_sale,
        'telegram_user': telegram_user,
        'req_type': 'SELL',
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
            action_type=user_data.get('action_type', 'መሸጥ'),
            property_type=user_data.get('property_type', ''),
            description=clean_description_text,
            price=price,
            phone=phone,
            photo_id=photo_id,
            extra_data=extra_data,
            photos=photos
        )
        
        if req_id:
            await update.message.reply_text(
                f"✅ <b>ማስታወቂያዎ በስኬት ተመዝግቧል!</b> 🎉\n\n"
                f"🆔 <b>የማስታወቂያ ቁጥር:</b> #ADK-{req_id}\n"
                f"📞 <b>ስልክ:</b> {phone}\n"
                + (f"📱 <b>Telegram:</b> {telegram_user}\n" if telegram_user else "") +
                f"\n📌 ማስታወቂያዎ ለደላሎች እና ለፈላጊዎች ተልኳል።",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
                parse_mode="HTML"
            )
            
            if photos:
                try:
                    await update.message.reply_photo(
                        photo=photos[0],
                        caption=f"📸 የማስታወቂያ #ADK-{req_id} ፎቶ",
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.error(f"Failed to send photo: {e}")
            
            listing_data = {
                'id': req_id,
                'main_category': user_data.get('main_category', ''),
                'sub_category': user_data.get('sub_category', ''),
                'price': price,
                'phone': phone,
                'action_type': user_data.get('action_type', 'መሸጥ'),
                'req_type': 'SELL',
                'description': clean_description_text,
                'extra_data': extra_data
            }
            
            notification_text = format_marketplace_card_md(listing_data)[0]
            
            try:
                await notify_brokers(context.bot, notification_text, req_id, user.id, photos)
                logger.info(f"✅ Notification sent to brokers for #ADK-{req_id}")
            except Exception as e:
                logger.error(f"Failed to notify brokers: {e}")
        else:
            await update.message.reply_text(
                "❌ <b>ማስታወቂያውን መመዝገብ አልተቻለም።</b>",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"❌ Seller save error: {e}", exc_info=True)
        await update.message.reply_text(
            f"❌ <b>ስህተት ተከስቷል:</b> {str(e)[:100]}",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="HTML"
        )
    
    context.user_data.clear()
    return ConversationHandler.END


# ==============================================================================
# 11-12. BROKER REGISTRATION & OFFER FLOW (እንዳሉ)
# ==============================================================================
# ... (ለአጭርነት አላሳየውም - እንደበፊቱ ይቆያል)

# ==============================================================================
# 13. VIEW REQUESTS / MARKETPLACE
# ==============================================================================

async def view_public_marketplace_md(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        page = context.user_data.get('marketplace_page', 0)
        limit = ITEMS_PER_PAGE
        offset = page * limit
        
        items = get_public_marketplace_items(limit=limit, offset=offset)
        total = count_listings(req_type="SELL")
        total_pages = (total + limit - 1) // limit if total else 1
        user_id = update.effective_user.id
        
        for item in items:
            item['_user_id'] = user_id
        
        if not items:
            await update.message.reply_text(
                "📭 ምንም ንብረቶች የሉም",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
            return
        
        await update.message.reply_text(
            f"*🛍️ ገበያ*  •  ገጽ {page+1}/{total_pages}  •  {len(items)} ንብረቶች",
            parse_mode="MarkdownV2"
        )
        
        for item in items:
            card_text, reply_markup = format_marketplace_card_md(item)
            
            photos = item.get('photos', [])
            if not photos:
                photo_id = item.get('photo_id')
                if photo_id:
                    photos = [photo_id]
            
            photo_io = None
            if photos and len(photos) > 0:
                photo_io = decode_base64_photo(photos[0])
            
            if photo_io:
                try:
                    await update.message.reply_photo(
                        photo=photo_io,
                        caption=card_text,
                        reply_markup=reply_markup,
                        parse_mode="MarkdownV2"
                    )
                except Exception as e:
                    logger.error(f"Photo error: {e}")
                    await update.message.reply_text(
                        card_text,
                        reply_markup=reply_markup,
                        parse_mode="MarkdownV2"
                    )
            else:
                await update.message.reply_text(
                    card_text,
                    reply_markup=reply_markup,
                    parse_mode="MarkdownV2"
                )
        
        nav_buttons = build_pagination_buttons(page, total_pages, "mpage")
        if nav_buttons:
            await update.message.reply_text(
                "📌 ገጽ ይለውጡ",
                reply_markup=nav_buttons
            )
    except Exception as e:
        logger.error(f"Marketplace error: {e}", exc_info=True)
        await update.message.reply_text("❌ ስህተት ተከስቷል። እባክዎ እንደገና ይሞክሩ።")

async def view_requests_md(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        is_admin = (user_id == ADMIN_CHAT_ID_INT)
        broker = get_broker(user_id)
        
        page = context.user_data.get('requests_page', 0)
        limit = ITEMS_PER_PAGE
        offset = page * limit
        
        listings = get_listings_by_category_ordered(limit=limit, offset=offset, req_type="BUY", order="ASC")
        total = count_listings(req_type="BUY")
        total_pages = (total + limit - 1) // limit if total else 1
        
        if not listings:
            await update.message.reply_text(
                f"📭 ምንም ጥያቄዎች የሉም",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
            return
        
        if is_admin:
            role = "👑 አድሚን"
        elif broker and broker.get('status') == 'approved':
            role = f"👤 {broker.get('full_name', 'ደላላ')}"
        else:
            role = "👤 ተጠቃሚ"
        
        await update.message.reply_text(
            f"*📋 የፈላጊዎች ዝርዝር*\n"
            f"{role}\n"
            f"🔔 ጠቅላላ: {total} ጥያቄዎች  •  ገጽ {page+1}/{total_pages}",
            parse_mode="MarkdownV2"
        )
        
        for listing in listings:
            card_text, reply_markup = format_buyer_request_md(listing)
            await update.message.reply_text(
                card_text,
                reply_markup=reply_markup,
                parse_mode="MarkdownV2"
            )
        
        nav_buttons = build_pagination_buttons(page, total_pages, "rpage")
        if nav_buttons:
            await update.message.reply_text(
                "📌 ገጽ ይለውጡ",
                reply_markup=nav_buttons
            )
    except Exception as e:
        logger.error(f"Requests error: {e}", exc_info=True)
        await update.message.reply_text("❌ ስህተት ተከስቷል። እባክዎ እንደገና ይሞክሩ።")

# ==============================================================================
# PAGINATION CALLBACKS
# ==============================================================================

async def marketplace_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        page = int(query.data.split('_')[1])
        context.user_data['marketplace_page'] = page
        try:
            await query.delete_message()
        except:
            pass
        await view_public_marketplace_md(update, context)
    except Exception as e:
        logger.error(f"Pagination error: {e}", exc_info=True)
        await query.message.reply_text("❌ ስህተት ተከስቷል። እባክዎ እንደገና ይሞክሩ።")

async def requests_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        page = int(query.data.split('_')[1])
        context.user_data['requests_page'] = page
        try:
            await query.delete_message()
        except:
            pass
        await view_requests_md(update, context)
    except Exception as e:
        logger.error(f"Pagination error: {e}", exc_info=True)
        await query.message.reply_text("❌ ስህተት ተከስቷል። እባክዎ እንደገና ይሞክሩ።")

async def view_brokers_directory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(sc, callback_data=f"dir_sc_{sc}")] for sc in SUB_CITIES]
    keyboard.append([InlineKeyboardButton("🌐 የሁሉም ክፍለ ከተሞች", callback_data="dir_sc_ሁሉም")])
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])

    await update.message.reply_text(
        "📍 **የደላሎችና አቅራቢዎች ማውጫ**\n\nእባክዎን ማየት የሚፈልጉበትን ክፍለ ከተማ ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def filter_brokers_by_subcity_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    sub_city = query.data.replace("dir_sc_", "")
    brokers = get_approved_brokers_directory(sub_city=sub_city)

    if not brokers:
        await query.edit_message_text(f"📭 በ{sub_city} ክፍለ ከተማ የተመዘገቡ ደላሎች አልተገኙም።")
        return

    msg = f"📋 **የተረጋገጡ ደላሎች ዝርዝር ({sub_city})፦**\n━━━━━━━━━━━━━━━━━━━\n\n"
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
        await query.answer("⛔ ይህን ማድረግ የሚችሉት አድሚን ብቻ ናቸው!", show_alert=True)
        return
    if data.startswith("admin_appr_"):
        broker_telegram_id = int(data.replace("admin_appr_", ""))
        success = update_broker_status(broker_telegram_id, "approved")
        if success:
            try:
                await query.edit_message_caption(
                    caption=f"{query.message.caption}\n\n✅ **ሁኔታ፦ ተፀድቋል (Approved)**",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            try:
                await context.bot.send_message(
                    chat_id=broker_telegram_id,
                    text=(
                        "🎉 **እንኳን ደስ አለዎት!**\n\n"
                        "የደላላ/አቅራቢ ምዝገባዎ በአድሚን ፀድቋል።\n"
                        "አሁን '📋 የፈላጊዎች ዝርዝር' በመጫን መስራት መጀመር ይችላሉ።"
                    ),
                    reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Failed to notify approved broker: {e}")
        else:
            await query.message.reply_text("❌ የደላላውን ሁኔታ መቀየር አልተቻለም።")
    elif data.startswith("admin_reje_"):
        broker_telegram_id = int(data.replace("admin_reje_", ""))
        success = update_broker_status(broker_telegram_id, "rejected")
        if success:
            try:
                await query.edit_message_caption(
                    caption=f"{query.message.caption}\n\n❌ **ሁኔታ፦ ተሰርዟል (Rejected)**",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            try:
                await context.bot.send_message(
                    chat_id=broker_telegram_id,
                    text="❌ **የምዝገባ ጥያቄዎ ውድቅ ተደርጓል!** እባክዎ እንደገና ይመዝገቡ።",
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
        await query.message.reply_text("❌ የተሳሳተ መረጃ ተላኳል።")
        return
    req_id = int(parts[-1])
    listing = get_listing_by_id(req_id)
    if not listing:
        await query.message.reply_text("❌ ጥያቄው አልተገኘም።")
        return
    if not is_admin and listing.get('user_chat_id') != user_id:
        await query.message.reply_text("⛔ ይህን ጥያቄ የማጥፋት ፈቃድ የለዎትም!")
        return
    success = update_listing_status(req_id, "deleted")
    if success:
        try:
            await query.edit_message_text(
                f"🗑️ **ጥያቄ #{req_id} በስኬት ተሰርዟል።**",
                parse_mode="Markdown"
            )
        except Exception:
            await query.message.reply_text(
                f"🗑️ **ጥያቄ #{req_id} በስኬት ተሰርዟል።**",
                parse_mode="Markdown"
            )
    else:
        await query.message.reply_text("❌ ጥያቄውን ማጥፋት አልተቻለም።")

async def nohave_item_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    broker = get_broker(user_id)
    if not broker or broker.get('status') != 'approved':
        await query.answer("⛔ ይህን ማድረግ የሚችሉት በአድሚን የተረጋገጡ ደላሎች ብቻ ናቸው!", show_alert=True)
        return
    parts = query.data.split('_')
    req_id = parts[-1] if parts else "?"
    await query.answer(f"ℹ️ ጥያቄ #{req_id} ተለፏል።", show_alert=False)
    try:
        await query.delete_message()
    except Exception:
        try:
            await query.edit_message_text(
                f"⏭️ **ጥያቄ #{req_id} ተለፏል።**",
                parse_mode="Markdown"
            )
        except Exception:
            pass

async def mark_sold_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    listing_id = int(data.replace("mark_sold_", ""))
    listing = get_listing_by_id(listing_id)
    if not listing:
        await query.answer("❌ ማስታወቂያው አልተገኘም።", show_alert=True)
        return
    if listing.get('user_chat_id') != user_id and user_id != ADMIN_CHAT_ID_INT:
        await query.answer("⛔ ይህን ማድረግ የሚችሉት የማስታወቂያው ባለቤት ወይም አድሚን ብቻ ነው!", show_alert=True)
        return
    success = update_listing_status(listing_id, "sold")
    if success:
        try:
            await query.edit_message_caption(
                caption=f"{query.message.caption}\n\n✅ **ይህ ንብረት ተሸጧል/ተከራይቷል!**",
                parse_mode="Markdown"
            )
        except Exception:
            await query.edit_message_text(
                f"✅ **ማስታወቂያ #ADK-{listing_id} እንደተሸጠ/እንደተከራየ ምልክት ተደርጎበታል!**",
                parse_mode="Markdown"
            )
        await query.answer("✅ ማስታወቂያው እንደተሸጠ ምልክት ተደርጎበታል!", show_alert=True)
    else:
        await query.answer("❌ ስህተት ተከስቷል።", show_alert=True)


# ==============================================================================
# 15. SUPPORT HANDLER
# ==============================================================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📞 **አዲካ ማርኬትፕሌስ - የደንበኞች ድጋፍ**\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "❓ **ቦቱን እንዴት መጠቀም ይቻላል?**\n\n"
        "1️⃣ **መግዛት / መከራየት፦** የሚፈልጉትን ቤት ወይም መኪና ፍላጎት ይመዝግቡ።\n"
        "2️⃣ **መሸጥ / ማከራየት፦** የሚሸጡትን ንብረት መረጃ እና ፎቶ በመጫን ለገበያ ያቅርቡ።\n"
        "3️⃣ **የደላሎች ማውጫ፦** በየክፍለ ከተማው የተረጋገጡ ደላሎችን ይመልከቱ።\n\n"
        "📲 **ለተጨማሪ ጥያቄ፦** ከአስተዳዳሪው ጋር ይገናኙ።"
    )
    keyboard = [
        [InlineKeyboardButton("💬 ከአስተዳዳሪው ጋር ይወያዩ", url="https://t.me/Adika_Admin")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    if update.message:
        await update.message.reply_text(help_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.edit_message_text(help_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


# ==============================================================================
# 16. NOTIFICATION PREFS
# ==============================================================================

async def notification_prefs_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    broker = get_broker(user_id)
    if not broker:
        await update.message.reply_text(
            "⛔ ይህን ማድረግ የሚችሉት የተመዘገቡ ደላሎች/አቅራቢዎች ብቻ ናቸው!",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return
    prefs = broker.get('notification_prefs', {})
    if isinstance(prefs, str):
        try: prefs = json.loads(prefs)
        except: prefs = {"car": True, "house": True, "price_min": 0, "price_max": 999999999, "enabled": True}
    enabled_text = "✅ በርተዋል" if prefs.get('enabled', True) else "❌ ጠፍተዋል"
    car_text = "✅" if prefs.get('car', True) else "❌"
    house_text = "✅" if prefs.get('house', True) else "❌"
    keyboard = [
        [InlineKeyboardButton(f"🔔 ማሳወቂያዎች፦ {enabled_text}", callback_data="notif_pref_toggle")],
        [InlineKeyboardButton(f"🚗 መኪና፦ {car_text}", callback_data="notif_pref_car"),
         InlineKeyboardButton(f"🏠 ቤት፦ {house_text}", callback_data="notif_pref_house")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    await update.message.reply_text(
        f"⚙️ **የማሳወቂያ ምርጫዎች**\n\n"
        f"🔔 **ሁኔታ፦** {enabled_text}\n"
        f"🚗 **መኪናᦄ {car_text}\n"
        f"🏠 **ቤት፦** {house_text}\n\n"
        f"ከታች ያሉትን ቁልፎች በመጠቀም ማስተካከል ይችላሉ።",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def notification_prefs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    broker = get_broker(user_id)
    if not broker:
        await query.answer("⛔ አልተፈቀደም!", show_alert=True)
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
    enabled_text = "✅ በርተዋል" if prefs.get('enabled', True) else "❌ ጠፍተዋል"
    car_text = "✅" if prefs.get('car', True) else "❌"
    house_text = "✅" if prefs.get('house', True) else "❌"
    keyboard = [
        [InlineKeyboardButton(f"🔔 ማሳወቂያዎች፦ {enabled_text}", callback_data="notif_pref_toggle")],
        [InlineKeyboardButton(f"🚗 መኪና፦ {car_text}", callback_data="notif_pref_car"),
         InlineKeyboardButton(f"🏠 ቤት፦ {house_text}", callback_data="notif_pref_house")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    try:
        await query.edit_message_text(
            f"⚙️ **የማሳወቂያ ምርጫዎች**\n\n"
            f"🔔 **ሁኔታ፦** {enabled_text}\n"
            f"🚗 **መኪና፦** {car_text}\n"
            f"🏠 **ቤት፦** {house_text}\n\n"
            f"ከታች ያሉትን ቁልፎች በመጠቀም ማስተካከል ይችላሉ።",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception:
        pass


# ==============================================================================
# 17. MAIN ENGINE
# ==============================================================================

def main():
    global bot_app

    init_db()
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    bot_app = app

    cancel_filter = filters.Regex("^🏠 ዋና ገጽ$")
    cancel_handler = MessageHandler(cancel_filter, go_home)

    # Buyer Conversation
    buyer_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 መግዛት / መከራየት$"), buyer_start)],
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

    # Seller Conversation
    seller_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 መሸጥ / ማከራየት$"), seller_start)],
        states={
            SELLER_MAIN: [CallbackQueryHandler(seller_category_chosen, pattern="^flow_sell_cat_"), cancel_handler],
            SELLER_ACTION: [CallbackQueryHandler(seller_action_chosen, pattern="^flow_sell_action_"), cancel_handler],
            SELLER_SUB: [CallbackQueryHandler(seller_sub_chosen, pattern="^flow_sell_sub_"), cancel_handler],
            SELLER_PROPERTY: [CallbackQueryHandler(seller_property_chosen, pattern="^flow_sell_prop_"), cancel_handler],
            SELLER_HTYPE: [CallbackQueryHandler(seller_htype_chosen, pattern="^flow_sell_htype_"), cancel_handler],
            SELLER_CONDITION: [
                CallbackQueryHandler(seller_condition_chosen, pattern="^flow_sell_cond_"),
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

    # Broker Registration
    broker_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 እንደ አቅራቢ/ደላላ መመዝገብ$"), broker_reg_start)],
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

    # Broker Offer Response
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

    # Register Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(buyer_conv)
    app.add_handler(seller_conv)
    app.add_handler(broker_conv)
    app.add_handler(broker_response_conv)

    # Message handlers
    app.add_handler(MessageHandler(filters.Regex("^🛍️ የገበያ ቦታ"), view_public_marketplace_md))
    app.add_handler(MessageHandler(filters.Regex("^📋 የፈላጊዎች ዝርዝር$"), view_requests_md))
    app.add_handler(MessageHandler(filters.Regex("^👥 የደላሎች/አቅራቢዎች ማውጫ$"), view_brokers_directory))
    app.add_handler(MessageHandler(filters.Regex("^📞 ድጋፍ$"), help_command))
    app.add_handler(MessageHandler(filters.Regex("^⚙️ የማሳወቂያ ምርጫ$"), notification_prefs_start))
    app.add_handler(CommandHandler("explorer", explorer_command))
    app.add_handler(cancel_handler)

    # Callback query handlers
    app.add_handler(CallbackQueryHandler(go_home, pattern="^flow_home$"))
    app.add_handler(CallbackQueryHandler(admin_approval_callback, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(delete_request_callback, pattern=r"^delete_req_"))
    app.add_handler(CallbackQueryHandler(nohave_item_callback, pattern="^nohave_item_"))
    app.add_handler(CallbackQueryHandler(filter_brokers_by_subcity_callback, pattern="^dir_sc_"))
    app.add_handler(CallbackQueryHandler(mark_sold_callback, pattern="^mark_sold_"))
    app.add_handler(CallbackQueryHandler(have_buyer_callback, pattern="^have_buyer_"))
    app.add_handler(CallbackQueryHandler(want_myself_callback, pattern="^want_myself_"))
    app.add_handler(CallbackQueryHandler(notification_prefs_callback, pattern="^notif_pref_"))
    app.add_handler(CallbackQueryHandler(marketplace_page_callback, pattern="^mpage_"))
    app.add_handler(CallbackQueryHandler(requests_page_callback, pattern="^rpage_"))

    logger.info("🚀 Adika Marketplace Bot በስኬት ተጀምሯል...")
    app.run_polling()


if __name__ == "__main__":
    main()
