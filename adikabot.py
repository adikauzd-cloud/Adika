

import logging
import os
import re
import asyncio
import threading
import json
from datetime import datetime
from typing import Optional, List, Dict, Any

import psycopg2
from psycopg2.extras import RealDictCursor
import sqlite3

from flask import Flask, request, jsonify, render_template_string, Response

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

SELLER_FORM_HTML = r"""
<!DOCTYPE html>
<html lang="am">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <title>ንብረት ለገበያ</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <script src="https://cdn.tailwindcss.com"></script>
  <script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
  <style>
    body { margin:0; background:#f8fafc; font-family:system-ui,-apple-system,sans-serif; -webkit-tap-highlight-color:transparent; }
    .chip-active { background:#2563eb; color:#fff; font-weight:700; box-shadow:0 1px 3px rgba(37,99,235,.3); }
    .chip-idle { background:#f3f4f6; color:#4b5563; border:1px solid #e5e7eb; }
    input, textarea, select { font-size: 16px !important; } /* prevent iOS zoom */
  </style>
</head>
<body>
  <div id="root"></div>
  <script type="text/babel">
    const { useState, useEffect, useRef } = React;
    const tg = window.Telegram.WebApp;
    tg.expand(); tg.ready();
    tg.setHeaderColor('#1e40af'); tg.setBackgroundColor('#f8fafc');

    const user = tg.initDataUnsafe?.user || {};
    const autoUsername = user.username ? '@' + user.username : '';
    const autoPhone = user.phone_number || '';

    function formatPrice(val) {
      const digits = String(val).replace(/[^\d]/g, '');
      if (!digits) return '';
      return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    }
    function parsePrice(val) {
      return String(val).replace(/[^\d]/g, '');
    }

    function Chip({ label, active, onClick, danger }) {
      return (
        <button type="button" onClick={onClick}
          className={`px-3 py-1.5 rounded-full text-xs whitespace-nowrap transition-all ${
            active
              ? (danger ? 'bg-red-500 text-white font-bold shadow-sm' : 'chip-active')
              : 'chip-idle'
          }`}>
          {label}
        </button>
      );
    }

    function ToggleCard({ active, onToggle, icon, label, danger }) {
      return (
        <button type="button" onClick={onToggle}
          className={`w-full flex items-center gap-3 p-3 rounded-xl border transition-all text-left ${
            active
              ? (danger ? 'bg-red-50 border-red-200 text-red-700' : 'bg-blue-50 border-blue-200 text-blue-700')
              : 'bg-gray-50 border-gray-200 text-gray-600'
          }`}>
          <div className={`w-10 h-6 rounded-full relative transition-colors ${active ? (danger ? 'bg-red-500' : 'bg-blue-600') : 'bg-gray-300'}`}>
            <div className={`absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${active ? 'translate-x-4' : 'translate-x-0.5'}`} />
          </div>
          <span className="text-sm font-medium">{icon} {label}</span>
        </button>
      );
    }

    function SellerForm() {
      const [step, setStep] = useState(1);
      const [category, setCategory] = useState('መኪና');
      // car fields
      const [fuel, setFuel] = useState('');
      const [transmission, setTransmission] = useState('');
      const [mileage, setMileage] = useState('');
      const [condition, setCondition] = useState('');
      const [carType, setCarType] = useState('');
      // house fields
      const [bedrooms, setBedrooms] = useState('');
      const [bathrooms, setBathrooms] = useState('');
      const [parking, setParking] = useState(false);
      const [houseCondition, setHouseCondition] = useState('');
      const [houseType, setHouseType] = useState('');
      // common
      const [price, setPrice] = useState('');
      const [negotiable, setNegotiable] = useState(true);
      const [urgent, setUrgent] = useState(false);
      const [description, setDescription] = useState('');
      const [phone, setPhone] = useState(autoPhone);
      const [telegramUser, setTelegramUser] = useState(autoUsername);
      const [photos, setPhotos] = useState([]); // data URLs
      const [status, setStatus] = useState('');
      const [submitting, setSubmitting] = useState(false);
      const fileRef = useRef(null);
      const [dragOver, setDragOver] = useState(false);

      const compressImage = (file) => new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = (e) => {
          const img = new Image();
          img.onload = () => {
            const canvas = document.createElement('canvas');
            let w = img.width, h = img.height;
            const max = 1200;
            if (w > max || h > max) {
              if (w > h) { h = (h / w) * max; w = max; }
              else { w = (w / h) * max; h = max; }
            }
            canvas.width = w; canvas.height = h;
            canvas.getContext('2d').drawImage(img, 0, 0, w, h);
            resolve(canvas.toDataURL('image/jpeg', 0.7));
          };
          img.src = e.target.result;
        };
        reader.readAsDataURL(file);
      });

      const addFiles = async (fileList) => {
        const files = Array.from(fileList || []).slice(0, 5 - photos.length);
        for (const f of files) {
          if (!f.type.startsWith('image/')) continue;
          const dataUrl = await compressImage(f);
          setPhotos(prev => prev.length < 5 ? [...prev, dataUrl] : prev);
        }
      };

      const removePhoto = (i) => setPhotos(prev => prev.filter((_, idx) => idx !== i));

      const canNext1 = category && (category === 'መኪና' ? (carType || condition) : (houseType || houseCondition));
      const canNext2 = parsePrice(price).length > 0;
      const canSubmit = phone && description;

      const submit = async () => {
        if (!canSubmit || submitting) return;
        setSubmitting(true);
        setStatus('');
        const isCar = category === 'መኪና';
        const data = {
          user_id: user.id || 'unknown',
          category,
          price: parsePrice(price),
          negotiable,
          urgent_sale: urgent,
          description,
          phone,
          telegram_user: telegramUser,
          photos,
          ...(isCar ? {
            fuel_type: fuel, transmission, mileage, condition, car_type: carType
          } : {
            bedrooms, bathrooms,
            parking: parking ? 'አለ' : 'የለም',
            condition: houseCondition, house_type: houseType
          })
        };
        try {
          const res = await fetch('/api/submit-listing', {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify(data)
          });
          const result = await res.json();
          if (result.status === 'success') {
            setStatus('ok');
            setTimeout(() => tg.close(), 2800);
          } else {
            setStatus(result.message || 'ስህተት');
            setSubmitting(false);
          }
        } catch (e) {
          setStatus('የኔትወርክ ስህተት');
          setSubmitting(false);
        }
      };

      const steps = ['መረጃ', 'ዋጋና ፎቶ', 'አድራሻ'];

      if (status === 'ok') {
        return (
          <div className="min-h-screen flex items-center justify-center p-6">
            <div className="text-center space-y-3">
              <div className="text-5xl">✅</div>
              <p className="font-bold text-lg text-green-700">ማስታወቂያዎ ተመዝግቧል!</p>
              <p className="text-sm text-gray-500">ለደላሎች ተልኳል…</p>
            </div>
          </div>
        );
      }

      return (
        <div className="min-h-screen pb-28">
          {/* Progress */}
          <div className="sticky top-0 z-20 bg-white/90 backdrop-blur border-b px-4 pt-3 pb-2">
            <h1 className="text-center font-bold text-sm text-gray-800 mb-2">ንብረት ለገበያ ያቅርቡ</h1>
            <div className="flex items-center gap-1">
              {steps.map((s, i) => (
                <React.Fragment key={s}>
                  <div className={`flex-1 text-center`}>
                    <div className={`mx-auto w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold ${
                      step > i+1 ? 'bg-blue-600 text-white' : step === i+1 ? 'bg-blue-600 text-white' : 'bg-gray-200 text-gray-500'
                    }`}>{i+1}</div>
                    <div className={`text-[10px] mt-0.5 ${step===i+1 ? 'text-blue-600 font-bold' : 'text-gray-400'}`}>{s}</div>
                  </div>
                  {i < 2 && <div className={`h-0.5 flex-1 mb-3 ${step > i+1 ? 'bg-blue-600' : 'bg-gray-200'}`} />}
                </React.Fragment>
              ))}
            </div>
          </div>

          <div className="p-4 space-y-4">
            {/* STEP 1 */}
            {step === 1 && (
              <div className="space-y-4">
                <div>
                  <label className="text-xs font-medium text-gray-600 mb-1.5 block">📦 ዋና ምድብ</label>
                  <div className="flex gap-2">
                    <Chip label="🚗 መኪና" active={category==='መኪና'} onClick={() => setCategory('መኪና')} />
                    <Chip label="🏠 ቤት" active={category==='ቤት'} onClick={() => setCategory('ቤት')} />
                  </div>
                </div>

                {category === 'መኪና' ? (
                  <>
                    <div>
                      <label className="text-xs font-medium text-gray-600 mb-1.5 block">🚗 አይነት</label>
                      <div className="flex gap-2 overflow-x-auto pb-1">
                        {['የቤት መኪና','የሥራ መኪና','ከባድ ተሽከርካሪ'].map(t =>
                          <Chip key={t} label={t} active={carType===t} onClick={() => setCarType(t)} />
                        )}
                      </div>
                    </div>
                    <div>
                      <label className="text-xs font-medium text-gray-600 mb-1.5 block">⛽ ነዳጅ</label>
                      <div className="flex gap-2 overflow-x-auto pb-1">
                        {['ቤንዚን','ናፍጣ','ኤሌክትሪክ','ሀይብሪድ'].map(t =>
                          <Chip key={t} label={t} active={fuel===t} onClick={() => setFuel(t)} />
                        )}
                      </div>
                    </div>
                    <div>
                      <label className="text-xs font-medium text-gray-600 mb-1.5 block">⚙️ ማርሽ</label>
                      <div className="flex gap-2">
                        {['ማንዋል','ኦቶማቲክ'].map(t =>
                          <Chip key={t} label={t} active={transmission===t} onClick={() => setTransmission(t)} />
                        )}
                      </div>
                    </div>
                    <div>
                      <label className="text-xs font-medium text-gray-600 mb-1.5 block">📊 ሁኔታ</label>
                      <div className="flex gap-2 overflow-x-auto pb-1">
                        {['አዲስ','ያገለገለ','ጥገና የሚፈልግ'].map(t =>
                          <Chip key={t} label={t} active={condition===t} onClick={() => setCondition(t)} />
                        )}
                      </div>
                    </div>
                    <div>
                      <label className="text-xs font-medium text-gray-600 mb-1.5 block">🛣️ ኪሎሜትር (KM)</label>
                      <input type="number" value={mileage} onChange={e => setMileage(e.target.value)}
                        placeholder="ለምሳሌ 50000"
                        className="w-full px-3 py-2.5 rounded-xl bg-gray-50 border border-gray-200 focus:bg-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none text-sm" />
                    </div>
                  </>
                ) : (
                  <>
                    <div>
                      <label className="text-xs font-medium text-gray-600 mb-1.5 block">🏠 አይነት</label>
                      <div className="flex gap-2 overflow-x-auto pb-1">
                        {['ቪላ','አፓርታማ','ኮንዶሚኒየም','ሪል እስቴት','መሬት'].map(t =>
                          <Chip key={t} label={t} active={houseType===t} onClick={() => setHouseType(t)} />
                        )}
                      </div>
                    </div>
                    <div>
                      <label className="text-xs font-medium text-gray-600 mb-1.5 block">🛏️ መኝታ</label>
                      <div className="flex gap-2">
                        {['1','2','3','4','5+'].map(t =>
                          <Chip key={t} label={t} active={bedrooms===t} onClick={() => setBedrooms(t)} />
                        )}
                      </div>
                    </div>
                    <div>
                      <label className="text-xs font-medium text-gray-600 mb-1.5 block">🛁 መታጠቢያ</label>
                      <div className="flex gap-2">
                        {['1','2','3','4+'].map(t =>
                          <Chip key={t} label={t} active={bathrooms===t} onClick={() => setBathrooms(t)} />
                        )}
                      </div>
                    </div>
                    <div>
                      <label className="text-xs font-medium text-gray-600 mb-1.5 block">📊 ሁኔታ</label>
                      <div className="flex gap-2 overflow-x-auto pb-1">
                        {['አዲስ','ጥሩ','እድሳት የሚፈልግ'].map(t =>
                          <Chip key={t} label={t} active={houseCondition===t} onClick={() => setHouseCondition(t)} />
                        )}
                      </div>
                    </div>
                    <ToggleCard active={parking} onToggle={() => setParking(!parking)} icon="🚗" label="ፓርኪንግ አለው" />
                  </>
                )}

                <div>
                  <label className="text-xs font-medium text-gray-600 mb-1.5 block">📝 መግለጫ</label>
                  <textarea value={description} onChange={e => setDescription(e.target.value)} rows={3}
                    placeholder="የንብረቱን ሙሉ ዝርዝር ያስገቡ..."
                    className="w-full px-3 py-2.5 rounded-xl bg-gray-50 border border-gray-200 focus:bg-white focus:ring-2 focus:ring-blue-500 outline-none text-sm resize-none" />
                </div>
              </div>
            )}

            {/* STEP 2 */}
            {step === 2 && (
              <div className="space-y-4">
                <div>
                  <label className="text-xs font-medium text-gray-600 mb-1.5 block">💰 ዋጋ (ብር)</label>
                  <div className="relative">
                    <input type="text" inputMode="numeric" value={price}
                      onChange={e => setPrice(formatPrice(e.target.value))}
                      placeholder="2,500,000"
                      className="w-full px-3 py-2.5 rounded-xl bg-gray-50 border border-gray-200 focus:bg-white focus:ring-2 focus:ring-blue-500 outline-none text-sm font-semibold" />
                    <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-400">ETB</span>
                  </div>
                </div>
                <ToggleCard active={negotiable} onToggle={() => setNegotiable(!negotiable)} icon="💰" label="ዋጋው የሚደራደር ነው" />
                <ToggleCard active={urgent} onToggle={() => setUrgent(!urgent)} icon="⚡" label="አስቸኳይ ሽያጭ" danger />

                {/* Drag-drop photos */}
                <div>
                  <label className="text-xs font-medium text-gray-600 mb-1.5 block">📸 ፎቶዎች (እስከ 5)</label>
                  <div
                    onDragOver={e => { e.preventDefault(); setDragOver(true); }}
                    onDragLeave={() => setDragOver(false)}
                    onDrop={e => { e.preventDefault(); setDragOver(false); addFiles(e.dataTransfer.files); }}
                    onClick={() => fileRef.current?.click()}
                    className={`border-2 border-dashed rounded-2xl p-5 text-center cursor-pointer transition-colors ${
                      dragOver ? 'border-blue-400 bg-blue-50' : 'border-gray-200 bg-gray-50/50'
                    }`}>
                    <div className="text-3xl mb-1">📷</div>
                    <p className="text-xs text-gray-500">ፎቶዎችን እዚህ ይስቀሉ (እስከ 5)</p>
                    <p className="text-[10px] text-gray-400 mt-0.5">ወይም ይጫኑ ለመምረጥ</p>
                    <input ref={fileRef} type="file" accept="image/*" multiple className="hidden"
                      onChange={e => { addFiles(e.target.files); e.target.value=''; }} />
                  </div>
                  {photos.length > 0 && (
                    <div className="grid grid-cols-3 gap-2 mt-3">
                      {photos.map((src, i) => (
                        <div key={i} className="relative aspect-square rounded-xl overflow-hidden border border-gray-100">
                          <img src={src} className="w-full h-full object-cover" alt="" />
                          <button type="button" onClick={(e) => { e.stopPropagation(); removePhoto(i); }}
                            className="absolute top-1 right-1 w-6 h-6 rounded-full bg-red-500 text-white text-xs flex items-center justify-center shadow">×</button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* STEP 3 */}
            {step === 3 && (
              <div className="space-y-4">
                <div>
                  <label className="text-xs font-medium text-gray-600 mb-1.5 block">📞 ስልክ ቁጥር</label>
                  <input type="tel" value={phone} onChange={e => setPhone(e.target.value)}
                    placeholder="0911223344"
                    className="w-full px-3 py-2.5 rounded-xl bg-gray-50 border border-gray-200 focus:bg-white focus:ring-2 focus:ring-blue-500 outline-none text-sm" />
                </div>
                <div>
                  <label className="text-xs font-medium text-gray-600 mb-1.5 block">📱 Telegram Username</label>
                  <input type="text" value={telegramUser} onChange={e => setTelegramUser(e.target.value)}
                    placeholder="@username"
                    className="w-full px-3 py-2.5 rounded-xl bg-gray-50 border border-gray-200 focus:bg-white focus:ring-2 focus:ring-blue-500 outline-none text-sm" />
                </div>
                {status && status !== 'ok' && (
                  <p className="text-sm text-red-600 text-center">{status}</p>
                )}
              </div>
            )}
          </div>

          {/* Bottom actions */}
          <div className="fixed bottom-0 left-0 right-0 p-3 bg-white/95 backdrop-blur border-t flex gap-2">
            {step > 1 ? (
              <button type="button" onClick={() => setStep(s => s-1)}
                className="w-1/3 py-3 rounded-xl bg-gray-100 text-gray-600 font-bold text-sm">ተመለስ</button>
            ) : (
              <button type="button" onClick={() => tg.close()}
                className="w-1/3 py-3 rounded-xl bg-gray-100 text-gray-600 font-bold text-sm">❌ ሰርዝ</button>
            )}
            {step < 3 ? (
              <button type="button" onClick={() => setStep(s => s+1)}
                disabled={step===1 ? !canNext1 : !canNext2}
                className="flex-1 py-3 rounded-xl bg-blue-600 text-white font-bold text-sm disabled:opacity-40">
                ቀጣይ →
              </button>
            ) : (
              <button type="button" onClick={submit} disabled={!canSubmit || submitting}
                className="flex-1 py-3 rounded-xl bg-blue-600 text-white font-bold text-sm disabled:opacity-40 flex items-center justify-center gap-1">
                {submitting ? 'እየተላከ...' : '🚀 መዝግብ'}
              </button>
            )}
          </div>
        </div>
      );
    }

    ReactDOM.createRoot(document.getElementById('root')).render(<SellerForm />);
  </script>
</body>
</html>
"""


BUYER_FORM_HTML = r"""
<!DOCTYPE html>
<html lang="am">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <title>ጥያቄ ያስገቡ</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <script src="https://cdn.tailwindcss.com"></script>
  <script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
  <style>
    body { margin:0; background:#f8fafc; font-family:system-ui,-apple-system,sans-serif; -webkit-tap-highlight-color:transparent; }
    .chip-active { background:#2563eb; color:#fff; font-weight:700; box-shadow:0 1px 3px rgba(37,99,235,.3); }
    .chip-idle { background:#f3f4f6; color:#4b5563; border:1px solid #e5e7eb; }
    input, textarea { font-size: 16px !important; }
  </style>
</head>
<body>
  <div id="root"></div>
  <script type="text/babel">
    const { useState } = React;
    const tg = window.Telegram.WebApp;
    tg.expand(); tg.ready();
    tg.setHeaderColor('#1e40af'); tg.setBackgroundColor('#f8fafc');

    const user = tg.initDataUnsafe?.user || {};
    const autoUsername = user.username ? '@' + user.username : '';
    const autoPhone = user.phone_number || '';

    function formatPrice(val) {
      const digits = String(val).replace(/[^\d]/g, '');
      if (!digits) return '';
      return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    }
    function parsePrice(val) {
      return String(val).replace(/[^\d]/g, '');
    }

    function Chip({ label, active, onClick }) {
      return (
        <button type="button" onClick={onClick}
          className={`px-3 py-1.5 rounded-full text-xs whitespace-nowrap transition-all ${active ? 'chip-active' : 'chip-idle'}`}>
          {label}
        </button>
      );
    }

    function BuyerForm() {
      const [category, setCategory] = useState('መኪና');
      const [budgetMin, setBudgetMin] = useState('');
      const [budgetMax, setBudgetMax] = useState('');
      const [createAlert, setCreateAlert] = useState(false);
      const [details, setDetails] = useState('');
      const [phone, setPhone] = useState(autoPhone);
      const [telegramUser, setTelegramUser] = useState(autoUsername);
      const [status, setStatus] = useState('');
      const [submitting, setSubmitting] = useState(false);

      const submit = async () => {
        if (!phone || !details || submitting) return;
        setSubmitting(true);
        setStatus('');
        const data = {
          user_id: user.id || 'unknown',
          category,
          budget_min: parsePrice(budgetMin),
          budget_max: parsePrice(budgetMax),
          create_alert: createAlert,
          details,
          phone,
          telegram_user: telegramUser
        };
        try {
          const res = await fetch('/api/submit-request', {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify(data)
          });
          const result = await res.json();
          if (result.status === 'success') {
            setStatus('ok');
            setTimeout(() => tg.close(), 2200);
          } else {
            setStatus(result.message || 'ስህተት');
            setSubmitting(false);
          }
        } catch (e) {
          setStatus('የኔትወርክ ስህተት');
          setSubmitting(false);
        }
      };

      if (status === 'ok') {
        return (
          <div className="min-h-screen flex items-center justify-center p-6">
            <div className="text-center space-y-3">
              <div className="text-5xl">✅</div>
              <p className="font-bold text-lg text-green-700">ጥያቄዎ ተመዝግቧል!</p>
              <p className="text-sm text-gray-500">አቅራቢዎች መልስ ይሰጡዎታል…</p>
            </div>
          </div>
        );
      }

      return (
        <div className="min-h-screen pb-28">
          <div className="sticky top-0 z-20 bg-white/90 backdrop-blur border-b px-4 py-3">
            <h1 className="text-center font-bold text-sm text-gray-800">የሚፈልጉትን ንብረት ይግለጹ</h1>
          </div>

          <div className="p-4 space-y-4">
            <div>
              <label className="text-xs font-medium text-gray-600 mb-1.5 block">📦 ምድብ</label>
              <div className="flex gap-2">
                <Chip label="🚗 መኪና" active={category==='መኪና'} onClick={() => setCategory('መኪና')} />
                <Chip label="🏠 ቤት" active={category==='ቤት'} onClick={() => setCategory('ቤት')} />
              </div>
            </div>

            <div>
              <label className="text-xs font-medium text-gray-600 mb-1.5 block">💰 የበጀት ክልል (ብር)</label>
              <div className="flex gap-2 items-center">
                <div className="flex-1 relative">
                  <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[10px] text-gray-400">ከ</span>
                  <input type="text" inputMode="numeric" value={budgetMin}
                    onChange={e => setBudgetMin(formatPrice(e.target.value))}
                    placeholder="500,000"
                    className="w-full pl-8 pr-2 py-2.5 rounded-xl bg-gray-50 border border-gray-200 focus:bg-white focus:ring-2 focus:ring-blue-500 outline-none text-sm" />
                </div>
                <span className="text-gray-300">—</span>
                <div className="flex-1 relative">
                  <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[10px] text-gray-400">እስከ</span>
                  <input type="text" inputMode="numeric" value={budgetMax}
                    onChange={e => setBudgetMax(formatPrice(e.target.value))}
                    placeholder="2,000,000"
                    className="w-full pl-10 pr-2 py-2.5 rounded-xl bg-gray-50 border border-gray-200 focus:bg-white focus:ring-2 focus:ring-blue-500 outline-none text-sm" />
                </div>
              </div>
            </div>

            {/* Notification preference card – correct Amharic */}
            <button type="button" onClick={() => setCreateAlert(!createAlert)}
              className={`w-full flex items-center gap-3 p-3.5 rounded-xl border transition-all text-left ${
                createAlert ? 'bg-blue-50 border-blue-200 text-blue-700' : 'bg-gray-50 border-gray-200 text-gray-600'
              }`}>
              <div className={`w-10 h-6 rounded-full relative transition-colors shrink-0 ${createAlert ? 'bg-blue-600' : 'bg-gray-300'}`}>
                <div className={`absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${createAlert ? 'translate-x-4' : 'translate-x-0.5'}`} />
              </div>
              <span className="text-sm font-medium leading-snug">🔔 ተመሳሳይ ንብረት ሲለቀቅ ማሳወቂያ ይድረሰኝ</span>
            </button>

            <div>
              <label className="text-xs font-medium text-gray-600 mb-1.5 block">📝 ዝርዝር ፍላጎት</label>
              <textarea value={details} onChange={e => setDetails(e.target.value)} rows={4}
                placeholder="ለምሳሌ፦ ቶዮታ ቪትዝ 2020፣ ነጭ፣ ኦቶማቲክ..."
                className="w-full px-3 py-2.5 rounded-xl bg-gray-50 border border-gray-200 focus:bg-white focus:ring-2 focus:ring-blue-500 outline-none text-sm resize-none" />
            </div>

            <div>
              <label className="text-xs font-medium text-gray-600 mb-1.5 block">📞 ስልክ ቁጥር</label>
              <input type="tel" value={phone} onChange={e => setPhone(e.target.value)}
                placeholder="0911223344"
                className="w-full px-3 py-2.5 rounded-xl bg-gray-50 border border-gray-200 focus:bg-white focus:ring-2 focus:ring-blue-500 outline-none text-sm" />
            </div>
            <div>
              <label className="text-xs font-medium text-gray-600 mb-1.5 block">📱 Telegram Username</label>
              <input type="text" value={telegramUser} onChange={e => setTelegramUser(e.target.value)}
                placeholder="@username"
                className="w-full px-3 py-2.5 rounded-xl bg-gray-50 border border-gray-200 focus:bg-white focus:ring-2 focus:ring-blue-500 outline-none text-sm" />
            </div>

            {status && status !== 'ok' && (
              <p className="text-sm text-red-600 text-center">{status}</p>
            )}
          </div>

          <div className="fixed bottom-0 left-0 right-0 p-3 bg-white/95 backdrop-blur border-t flex gap-2">
            <button type="button" onClick={() => tg.close()}
              className="w-1/3 py-3 rounded-xl bg-gray-100 text-gray-600 font-bold text-sm">❌ ሰርዝ</button>
            <button type="button" onClick={submit} disabled={!phone || !details || submitting}
              className="flex-1 py-3 rounded-xl bg-blue-600 text-white font-bold text-sm disabled:opacity-40 flex items-center justify-center gap-1">
              {submitting ? 'እየተላከ...' : '📨 ጥያቄውን ላክ'}
            </button>
          </div>
        </div>
      );
    }

    ReactDOM.createRoot(document.getElementById('root')).render(<BuyerForm />);
  </script>
</body>
</html>
"""



@web_app.route('/')
def home():
   return "✅ Adika Marketplace Bot በስኬት እየሰራ ይገኛል!", 200

@web_app.route('/seller-form')
def webapp_seller_form():
   return Response(SELLER_FORM_HTML, mimetype='text/html; charset=utf-8')

@web_app.route('/buyer-form')
def webapp_buyer_form():
   return Response(BUYER_FORM_HTML, mimetype='text/html; charset=utf-8')

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


# ==============================================================================
# WEB APP EXPLORER (React + Tailwind) - Full Production UI
# Features: Relative time, Mark as Sold, View booster, 2-col grid, Delete, Status
# ==============================================================================

EXPLORER_HTML = r"""
<!DOCTYPE html>
<html lang="am">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <title>Adika Explorer</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <script src="https://cdn.tailwindcss.com"></script>
  <script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
  <style>
    body { background: #f1f5f9; margin: 0; font-family: system-ui, -apple-system, sans-serif; -webkit-tap-highlight-color: transparent; }
    .glass { background: rgba(255,255,255,0.88); backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px); }
    .glass-dark { background: rgba(0,0,0,0.48); backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px); }
    .line-clamp-1 { display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; overflow: hidden; }
    .line-clamp-3 { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
    .aspect-4-3 { aspect-ratio: 4/3; }
    .sold-overlay { background: rgba(0,0,0,0.55); }
    @keyframes pulse-skel { 0%,100%{opacity:1} 50%{opacity:.45} }
    .skel { animation: pulse-skel 1.4s ease-in-out infinite; background: #e2e8f0; }
    .no-scrollbar::-webkit-scrollbar { display: none; }
    .no-scrollbar { -ms-overflow-style: none; scrollbar-width: none; }
    .modal-enter { animation: fadeIn 0.2s ease; }
    @keyframes fadeIn { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: none; } }
  </style>
</head>
<body>
  <div id="root"></div>
  <script type="text/babel">
    const { useState, useEffect, useCallback, useRef } = React;

    const tg = window.Telegram.WebApp;
    tg.expand();
    tg.ready();
    tg.setHeaderColor('#1e40af');
    tg.setBackgroundColor('#f1f5f9');
    const currentUserId = tg.initDataUnsafe?.user?.id || null;

    function relativeTime(iso) {
      if (!iso) return '';
      const d = new Date(iso);
      if (isNaN(d)) return '';
      const sec = Math.floor((Date.now() - d.getTime()) / 1000);
      if (sec < 45) return 'Just now';
      if (sec < 3600) return Math.floor(sec / 60) + 'm ago';
      if (sec < 86400) return Math.floor(sec / 3600) + 'h ago';
      if (sec < 604800) return Math.floor(sec / 86400) + 'd ago';
      if (sec < 2592000) return Math.floor(sec / 604800) + 'w ago';
      return Math.floor(sec / 2592000) + 'mo ago';
    }

    const viewedThisSession = new Set();

    function SkeletonCard() {
      return (
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
          <div className="aspect-4-3 skel" />
          <div className="p-2.5 space-y-2">
            <div className="h-3 w-3/4 skel rounded" />
            <div className="h-2.5 w-1/2 skel rounded" />
            <div className="h-4 w-2/3 skel rounded" />
            <div className="flex gap-1.5"><div className="h-8 flex-1 skel rounded-xl" /><div className="h-8 flex-1 skel rounded-xl" /></div>
          </div>
        </div>
      );
    }

    /* ---------- Item Detail Modal ---------- */
    function ItemDetailModal({ item, onClose, onStatusChange, onDelete, currentUid }) {
      const extra = item.extra_data || {};
      const isSell = (item.req_type || '').toUpperCase() === 'SELL';
      const photos = item.photos || [];
      const status = (item.status || 'pending').toLowerCase();
      const isSold = ['sold','rented','expired'].includes(status);
      const isOwner = currentUid && String(item.user_chat_id) === String(currentUid);
      const [photoIdx, setPhotoIdx] = useState(0);
      const [confirmDel, setConfirmDel] = useState(false);

      const markStatus = async (s) => {
        try {
          const res = await fetch(`/api/items/${item.id}/status`, {
            method: 'PATCH', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ status: s, user_id: currentUid })
          });
          const d = await res.json();
          if (d.status === 'success') { onStatusChange(item.id, s); onClose(); }
        } catch(e) {}
      };
      const doDelete = async () => {
        try {
          const res = await fetch(`/api/items/${item.id}`, {
            method: 'DELETE', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ user_id: currentUid })
          });
          const d = await res.json();
          if (d.status === 'success') { onDelete(item.id); onClose(); }
        } catch(e) {}
      };

      return (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-end sm:items-center justify-center modal-enter" onClick={onClose}>
          <div className="bg-white w-full max-w-md max-h-[92vh] rounded-t-3xl sm:rounded-3xl overflow-hidden flex flex-col shadow-2xl" onClick={e => e.stopPropagation()}>
            {/* Image carousel */}
            <div className="relative aspect-4-3 bg-gray-900/5 shrink-0 flex items-center justify-center overflow-hidden border-b border-black/[0.06]">
              {photos.length > 0 ? (
                <img src={photos[photoIdx]} className="max-w-full max-h-full w-full h-full object-contain" alt=""
                  onError={e => e.target.style.display='none'} />
              ) : (
                <div className="w-full h-full flex items-center justify-center text-5xl">
                  {item.main_category === 'መኪና' ? '🚗' : '🏠'}
                </div>
              )}
              {photos.length > 1 && (
                <div className="absolute bottom-3 left-0 right-0 flex justify-center gap-1.5">
                  {photos.map((_, i) => (
                    <button key={i} onClick={() => setPhotoIdx(i)}
                      className={`w-2 h-2 rounded-full ${i===photoIdx ? 'bg-white' : 'bg-white/40'}`} />
                  ))}
                </div>
              )}
              <button onClick={onClose} className="absolute top-3 right-3 w-8 h-8 rounded-full bg-black/40 text-white flex items-center justify-center text-lg">×</button>
              {isSold && (
                <div className="absolute inset-0 sold-overlay flex items-center justify-center">
                  <span className="text-white font-bold px-4 py-1.5 rounded-full bg-black/60 text-sm">
                    {status==='rented' ? '✅ ተከራይቷል' : status==='expired' ? '⏳ ጊዜው አልፏል' : '✅ ተሸጧል'}
                  </span>
                </div>
              )}
            </div>

            <div className="p-4 overflow-y-auto flex-1 space-y-3">
              <div className="flex items-start justify-between gap-2">
                <h2 className="font-bold text-base text-gray-900 leading-snug">
                  {item.main_category}{item.sub_category ? ` • ${String(item.sub_category).replace(/[🚗🚚🚜🏡🏢🏞️]/g,'').trim()}` : ''}
                </h2>
                <span className="text-[10px] text-gray-400 shrink-0">{relativeTime(item.created_at)}</span>
              </div>
              <div className="text-lg font-bold text-blue-700">
                {isSell ? '💰 ዋጋ' : '💰 በጀት'}: {item.price || '—'} ብር
                {extra.negotiable && <span className="text-xs font-normal text-green-600 ml-1">(የሚደራደር)</span>}
                {extra.urgent_sale && <span className="text-xs text-red-500 ml-1">⚡ አስቸኳይ</span>}
              </div>
              <p className="text-sm text-gray-600 whitespace-pre-wrap leading-relaxed">
                {(item.description || '').replace(/[📝💰📞⚡📢🔄📦]/g,'').trim() || 'መግለጫ የለም'}
              </p>
              <div className="flex flex-wrap gap-2 text-[11px] text-gray-500">
                <span className="bg-gray-100 px-2 py-1 rounded-lg">👀 {item.view_count || 0} እይታዎች</span>
                <span className="bg-gray-100 px-2 py-1 rounded-lg">#{item.id}</span>
                {item.phone && <span className="bg-gray-100 px-2 py-1 rounded-lg">📞 {item.phone}</span>}
              </div>

              {/* Contact actions */}
              {!isSold && (
                <div className="flex gap-2 pt-1">
                  <a href={item.phone ? `tel:${String(item.phone).replace(/\s+/g,'')}` : '#'}
                    className="flex-1 py-3 rounded-xl bg-blue-500/15 text-blue-700 border border-blue-500/30 text-sm font-bold text-center">📞 ደውል</a>
                  {extra.telegram_user && (
                    <a href={`https://t.me/${String(extra.telegram_user).replace('@','')}`} target="_blank" rel="noreferrer"
                      className="flex-1 py-3 rounded-xl bg-blue-500/15 text-blue-700 border border-blue-500/30 text-sm font-bold text-center">💬 ቻት</a>
                  )}
                </div>
              )}

              {/* Owner controls */}
              {isOwner && (
                <div className="border-t pt-3 space-y-2">
                  <p className="text-xs font-medium text-gray-500">የባለቤት ቁጥጥር</p>
                  <div className="flex flex-wrap gap-2">
                    {!isSold && (
                      <>
                        <button onClick={() => markStatus('sold')} className="px-3 py-2 rounded-xl bg-red-50 text-red-600 text-xs font-bold border border-red-100">✅ ተሸጧል</button>
                        <button onClick={() => markStatus('rented')} className="px-3 py-2 rounded-xl bg-orange-50 text-orange-600 text-xs font-bold border border-orange-100">🔑 ተከራይቷል</button>
                      </>
                    )}
                    {isSold && (
                      <button onClick={() => markStatus('pending')} className="px-3 py-2 rounded-xl bg-green-50 text-green-700 text-xs font-bold border border-green-100">🔄 እንደገና ንቁ</button>
                    )}
                    <button onClick={() => setConfirmDel(true)} className="px-3 py-2 rounded-xl bg-gray-100 text-gray-700 text-xs font-bold">🗑️ አጥፋ</button>
                  </div>
                </div>
              )}
            </div>

            {confirmDel && (
              <div className="absolute inset-0 bg-black/40 flex items-center justify-center p-6 z-10">
                <div className="bg-white rounded-2xl p-5 w-full max-w-xs shadow-xl">
                  <p className="font-bold text-center mb-1">እርግጠኛ ነዎት?</p>
                  <p className="text-sm text-gray-500 text-center mb-4">#{item.id} ይጠፋል።</p>
                  <div className="flex gap-2">
                    <button onClick={() => setConfirmDel(false)} className="flex-1 py-2.5 rounded-xl bg-gray-100 text-sm font-medium">ሰርዝ</button>
                    <button onClick={doDelete} className="flex-1 py-2.5 rounded-xl bg-red-600 text-white text-sm font-medium">አጥፋ</button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      );
    }

    /* ---------- Card ---------- */
    function Card({ item, onOpen, onStatusChange, onDelete, currentUid }) {
      const cardRef = useRef(null);
      const extra = item.extra_data || {};
      const isSell = (item.req_type || '').toUpperCase() === 'SELL';
      const photos = item.photos || [];
      const status = (item.status || 'pending').toLowerCase();
      const isSold = ['sold','rented','expired'].includes(status);
      const isOwner = currentUid && String(item.user_chat_id) === String(currentUid);
      const [menuOpen, setMenuOpen] = useState(false);
      const [localViews, setLocalViews] = useState(item.view_count || 0);

      useEffect(() => {
        if (!cardRef.current || viewedThisSession.has(item.id) || isSold) return;
        const obs = new IntersectionObserver(([entry]) => {
          if (entry.isIntersecting && entry.intersectionRatio >= 0.5) {
            viewedThisSession.add(item.id);
            fetch(`/api/views/${item.id}`, { method: 'POST' })
              .then(r => r.json())
              .then(d => { if (d.view_count) setLocalViews(d.view_count); })
              .catch(() => {});
            obs.disconnect();
          }
        }, { threshold: 0.5 });
        obs.observe(cardRef.current);
        return () => obs.disconnect();
      }, [item.id, isSold]);

      const markStatus = async (s) => {
        setMenuOpen(false);
        try {
          const res = await fetch(`/api/items/${item.id}/status`, {
            method: 'PATCH', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ status: s, user_id: currentUid })
          });
          const d = await res.json();
          if (d.status === 'success') onStatusChange(item.id, s);
        } catch(e) {}
      };

      const statusBadge = () => {
        if (status === 'sold') return <span className="text-[9px] font-bold text-white bg-red-500/90 px-1.5 py-0.5 rounded-full">✅ ተሸጧል</span>;
        if (status === 'rented') return <span className="text-[9px] font-bold text-white bg-orange-500/90 px-1.5 py-0.5 rounded-full">✅ ተከራይቷል</span>;
        if (status === 'expired') return <span className="text-[9px] font-bold text-white bg-gray-500/90 px-1.5 py-0.5 rounded-full">⏳ አልፏል</span>;
        const cat = item.main_category === 'መኪና' ? '🚗' : '🏠';
        return <span className="text-[9px] font-bold text-white bg-emerald-500/90 px-1.5 py-0.5 rounded-full">{cat} ንቁ</span>;
      };

      return (
        <div ref={cardRef}
          className="bg-white rounded-2xl border border-black/[0.08] shadow-sm hover:shadow-md transition-shadow overflow-hidden relative active:scale-[0.98]">
          {/* Photo – opens modal */}
          <div className="relative aspect-4-3 bg-gradient-to-br from-slate-50 to-blue-50 cursor-pointer" onClick={() => onOpen(item)}>
            {photos.length > 0 ? (
              <img src={photos[0]} alt="" className="w-full h-full object-cover" loading="lazy"
                onError={e => { e.target.style.display='none'; }} />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-3xl opacity-70">
                {item.main_category === 'መኪና' ? '🚗' : '🏠'}
              </div>
            )}
            {isSold && (
              <div className="absolute inset-0 sold-overlay flex items-center justify-center pointer-events-none">
                <span className="text-white font-bold text-[11px] px-2.5 py-1 rounded-full bg-black/55">
                  {status==='rented' ? '✅ ተከራይቷል' : status==='expired' ? '⏳ አልፏል' : '✅ ተሸጧል'}
                </span>
              </div>
            )}
            <div className="absolute top-1.5 left-1.5">{statusBadge()}</div>
            {isOwner && (
              <div className="absolute top-1.5 right-1.5" onClick={e => e.stopPropagation()}>
                <button onClick={() => setMenuOpen(!menuOpen)}
                  className="w-7 h-7 rounded-full glass-dark text-white text-sm flex items-center justify-center">⋮</button>
                {menuOpen && (
                  <div className="absolute right-0 mt-1 w-32 bg-white rounded-xl shadow-lg border border-gray-100 text-[11px] z-20 overflow-hidden">
                    {!isSold && (
                      <>
                        <button onClick={() => markStatus('sold')} className="w-full text-left px-3 py-2 hover:bg-gray-50">✅ ተሸጧል</button>
                        <button onClick={() => markStatus('rented')} className="w-full text-left px-3 py-2 hover:bg-gray-50">🔑 ተከራይቷል</button>
                      </>
                    )}
                    {isSold && <button onClick={() => markStatus('pending')} className="w-full text-left px-3 py-2 hover:bg-gray-50">🔄 ንቁ አድርግ</button>}
                    <button onClick={() => { setMenuOpen(false); onOpen(item); }} className="w-full text-left px-3 py-2 hover:bg-gray-50 text-blue-600">📋 ዝርዝር</button>
                  </div>
                )}
              </div>
            )}
            {/* Bottom glass badge: views + time */}
            <div className="absolute bottom-1.5 left-1.5 right-1.5 flex justify-between pointer-events-none">
              <span className="glass-dark text-[9px] text-white px-1.5 py-0.5 rounded-full">👀 {localViews}</span>
              <span className="glass-dark text-[9px] text-white px-1.5 py-0.5 rounded-full">{relativeTime(item.created_at)}</span>
            </div>
          </div>

          {/* Content */}
          <div className="p-2.5 space-y-1">
            <h3 className="font-bold text-gray-900 text-[12px] line-clamp-1 leading-tight" onClick={() => onOpen(item)}>
              {item.main_category}{item.sub_category ? ` • ${String(item.sub_category).replace(/[🚗🚚🚜🏡🏢🏞️]/g,'').trim()}` : ''}
            </h3>
            <p className="text-[10px] text-gray-500 line-clamp-1">
              {(item.description || '').replace(/[📝💰📞⚡📢🔄📦]/g,'').slice(0, 42)}
            </p>
            <div className="text-[13px] font-bold text-blue-700">
              {isSell ? '💰 ዋጋ' : '💰 በጀት'}: {item.price || '—'}
              {extra.urgent_sale && <span className="text-red-500 text-[10px] ml-0.5">⚡</span>}
            </div>
            <div className="flex gap-1.5 pt-0.5">
              <a href={!isSold && item.phone ? `tel:${String(item.phone).replace(/\s+/g,'')}` : undefined}
                onClick={e => { if (isSold || !item.phone) e.preventDefault(); }}
                className={`flex-1 py-2 rounded-xl text-[11px] font-bold flex items-center justify-center gap-0.5 ${isSold ? 'bg-gray-100 text-gray-400' : 'bg-blue-500/15 text-blue-700 border border-blue-500/30'}`}>
                📞 ደውል
              </a>
              {extra.telegram_user ? (
                <a href={!isSold ? `https://t.me/${String(extra.telegram_user).replace('@','')}` : undefined}
                  target="_blank" rel="noreferrer"
                  onClick={e => { if (isSold) e.preventDefault(); }}
                  className={`flex-1 py-2 rounded-xl text-[11px] font-bold flex items-center justify-center gap-0.5 ${isSold ? 'bg-gray-100 text-gray-400' : 'bg-blue-500/15 text-blue-700 border border-blue-500/30'}`}>
                  💬 ቻት
                </a>
              ) : null}
            </div>
          </div>
        </div>
      );
    }

    /* ---------- App ---------- */
    function App() {
      const params = new URLSearchParams(window.location.search);
      const initialTab = params.get('tab') === 'requests' ? 'requests' : 'marketplace';
      const [tab, setTab] = useState(initialTab);
      const [items, setItems] = useState([]);
      const [page, setPage] = useState(1);
      const [hasMore, setHasMore] = useState(false);
      const [loading, setLoading] = useState(true);
      const [filters, setFilters] = useState({ q: '', category: '' });
      const [searchInput, setSearchInput] = useState('');
      const [detailItem, setDetailItem] = useState(null);
      const cacheRef = useRef({}); // client-side tab/category cache

      const loadData = useCallback(async (pageNum = 1, append = false) => {
        const cacheKey = `${tab}|${filters.category}|${filters.q}|${pageNum}`;
        if (!append && cacheRef.current[cacheKey]) {
          const cached = cacheRef.current[cacheKey];
          setItems(cached.items);
          setHasMore(cached.has_more);
          setPage(pageNum);
          setLoading(false);
          return;
        }
        setLoading(true);
        try {
          const qs = new URLSearchParams({
            page: pageNum, limit: 12,
            type: tab === 'marketplace' ? 'SELL' : 'BUY',
            order: 'DESC', active_only: '1',
            ...Object.fromEntries(Object.entries(filters).filter(([,v]) => v))
          });
          const res = await fetch(`/api/explorer/listings?${qs}`);
          const data = await res.json();
          if (data.status === 'success') {
            setItems(prev => append ? [...prev, ...data.items] : data.items);
            setHasMore(data.has_more);
            setPage(pageNum);
            if (!append) {
              cacheRef.current[cacheKey] = { items: data.items, has_more: data.has_more };
            }
          }
        } catch(e) { console.error(e); }
        finally { setLoading(false); }
      }, [tab, filters]);

      // Reload on tab / category change
      useEffect(() => { loadData(1, false); }, [tab, filters.category, filters.q]);

      // Debounce search input → filters.q (300ms)
      useEffect(() => {
        const t = setTimeout(() => {
          setFilters(f => f.q === searchInput ? f : {...f, q: searchInput});
        }, 300);
        return () => clearTimeout(t);
      }, [searchInput]);

      const onStatusChange = (id, s) => setItems(prev => prev.map(it => it.id === id ? {...it, status: s} : it));
      const onDelete = (id) => setItems(prev => prev.filter(it => it.id !== id));

      return (
        <div className="min-h-screen pb-16">
          {/* Sticky glass header */}
          <div className="sticky top-0 z-30 glass border-b border-gray-200/60">
            <div className="flex">
              <button onClick={() => setTab('marketplace')}
                className={`flex-1 py-2.5 text-xs font-bold transition ${tab==='marketplace' ? 'text-blue-600 border-b-2 border-blue-600' : 'text-gray-500'}`}>
                🛒 የገበያ ቦታ
              </button>
              <button onClick={() => setTab('requests')}
                className={`flex-1 py-2.5 text-xs font-bold transition ${tab==='requests' ? 'text-blue-600 border-b-2 border-blue-600' : 'text-gray-500'}`}>
                📋 የፈላጊዎች
              </button>
            </div>
            {/* Search with icon */}
            <div className="px-2.5 pt-2 pb-1.5">
              <div className="relative">
                <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 text-sm pointer-events-none">🔍</span>
                <input type="search" placeholder="ፈልግ..." value={searchInput}
                  onChange={e => setSearchInput(e.target.value)}
                  className="w-full pl-9 pr-3 py-2 bg-gray-50/80 border border-gray-200 rounded-xl text-xs focus:outline-none focus:ring-2 focus:ring-blue-200 focus:bg-white" />
              </div>
            </div>
            {/* Glassmorphism category pills */}
            <div className="px-2.5 pb-2 flex gap-2 overflow-x-auto no-scrollbar" style={{WebkitOverflowScrolling:'touch'}}>
              {[
                {id:'', label:'✨ ሁሉም'},
                {id:'መኪና', label:'🚗 መኪና'},
                {id:'ቤት', label:'🏠 ቤት / ቦታ'},
                {id:'ንግድ', label:'🏢 የሥራ ቦታ / ንግድ'},
              ].map(cat => (
                <button key={cat.id || 'all'} type="button"
                  onClick={() => setFilters(f => ({...f, category: cat.id}))}
                  className={`shrink-0 px-3.5 py-1.5 rounded-2xl text-[11px] font-medium transition-all whitespace-nowrap ${
                    filters.category === cat.id
                      ? 'bg-blue-600 text-white font-bold shadow-md shadow-blue-500/20 border border-transparent'
                      : 'backdrop-blur-md bg-white/40 border border-white/60 shadow-sm text-gray-800'
                  }`}>
                  {cat.label}
                </button>
              ))}
            </div>
          </div>

          {/* 2-col grid */}
          <div className="p-2.5 grid grid-cols-2 gap-2.5">
            {loading && items.length === 0 && Array.from({length: 6}).map((_,i) => <SkeletonCard key={i} />)}
            {items.map(item => (
              <Card key={item.id} item={item} currentUid={currentUserId}
                onOpen={setDetailItem} onStatusChange={onStatusChange} onDelete={onDelete} />
            ))}
          </div>

          {!loading && items.length === 0 && (
            <div className="text-center py-16 text-gray-400">
              <div className="text-4xl mb-2">📭</div>
              <p className="text-sm">ምንም ንብረት አልተገኘም</p>
            </div>
          )}
          {hasMore && !loading && (
            <div className="text-center pb-6">
              <button onClick={() => loadData(page+1, true)}
                className="bg-white border border-blue-200 text-blue-600 px-5 py-2 rounded-full text-xs font-medium shadow-sm">
                ተጨማሪ ይመልከቱ
              </button>
            </div>
          )}
          {loading && items.length > 0 && <div className="text-center py-3 text-xs text-gray-400">እየጫነ ነው...</div>}

          {detailItem && (
            <ItemDetailModal item={detailItem} currentUid={currentUserId}
              onClose={() => setDetailItem(null)}
              onStatusChange={onStatusChange} onDelete={onDelete} />
          )}
        </div>
      );
    }

    ReactDOM.createRoot(document.getElementById('root')).render(<App />);
  </script>
</body>
</html>
"""



@web_app.route('/explorer')
def explorer_page():
    return Response(EXPLORER_HTML, mimetype='text/html; charset=utf-8')


@web_app.route('/api/explorer/listings', methods=['GET'])
def api_explorer_listings():
    """Fetch listings/requests with pagination, filters, relative-ready timestamps."""
    try:
        page = max(1, int(request.args.get('page', 1)))
        limit = min(50, max(1, int(request.args.get('limit', 12))))
        offset = (page - 1) * limit
        req_type = request.args.get('type', '').upper()
        category = request.args.get('category', '')
        search = request.args.get('q', '').strip()
        order = request.args.get('order', 'DESC').upper()
        active_only = request.args.get('active_only', '1') == '1'
        if order not in ('ASC', 'DESC'):
            order = 'DESC'

        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()

        where = ["status != 'deleted'"]
        params = []

        if active_only:
            where.append("status NOT IN ('sold', 'rented', 'expired')")
        if req_type in ('SELL', 'BUY'):
            where.append(f"UPPER(req_type) = UPPER({p})")
            params.append(req_type)
        if category:
            where.append(f"main_category = {p}")
            params.append(category)
        if search:
            if DATABASE_URL:
                where.append(f"(description ILIKE {p} OR price ILIKE {p} OR phone ILIKE {p})")
            else:
                where.append(f"(description LIKE {p} OR price LIKE {p} OR phone LIKE {p})")
            params.extend([f'%{search}%'] * 3)

        where_sql = " AND ".join(where)
        order_sql = "ASC" if order == "ASC" else "DESC"

        cur.execute(f"SELECT COUNT(*) as cnt FROM listings WHERE {where_sql}", params)
        total_row = cur.fetchone()
        total = total_row['cnt'] if isinstance(total_row, dict) else (total_row[0] if total_row else 0)

        cur.execute(f"""
            SELECT * FROM listings
            WHERE {where_sql}
            ORDER BY id {order_sql}
            LIMIT {p} OFFSET {p}
        """, params + [limit, offset])

        rows = cur.fetchall()
        items = []
        for row in rows:
            item = dict(row) if isinstance(row, dict) else dict(zip([c[0] for c in cur.description], row))
            if isinstance(item.get('extra_data'), str):
                try:
                    item['extra_data'] = json.loads(item['extra_data'])
                except Exception:
                    item['extra_data'] = {}
            # photos
            cur.execute(f"SELECT photo_id FROM listing_photos WHERE listing_id = {p}", (item['id'],))
            photos = [r['photo_id'] if isinstance(r, dict) else r[0] for r in cur.fetchall()]
            if not photos and item.get('photo_id'):
                photos = [item['photo_id']]
            item['photos'] = photos
            # Ensure view_count baseline for old rows
            if item.get('view_count') is None:
                item['view_count'] = 0
            # Serialize created_at for frontend
            if item.get('created_at') and not isinstance(item['created_at'], str):
                try:
                    item['created_at'] = item['created_at'].isoformat()
                except Exception:
                    item['created_at'] = str(item['created_at'])
            items.append(item)

        conn.close()
        return jsonify({
            "status": "success",
            "page": page,
            "limit": limit,
            "total": total,
            "has_more": offset + limit < total,
            "items": items
        })
    except Exception as e:
        logger.error(f"api_explorer_listings error: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@web_app.route('/api/views/<int:listing_id>', methods=['POST'])
def api_view_booster(listing_id):
    """
    Social-proof view booster.
    Increments view_count by a random amount between +3 and +7.
    Called once per card per session from the frontend IntersectionObserver.
    """
    import random
    try:
        boost = random.randint(3, 7)
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        # Ensure baseline exists for brand-new rows that still have 0
        cur.execute(f"SELECT view_count FROM listings WHERE id = {p}", (listing_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({"status": "error", "message": "not found"}), 404
        current = row['view_count'] if isinstance(row, dict) else row[0]
        if current is None or current == 0:
            # Assign initial baseline 35–90 then add boost
            baseline = random.randint(35, 90)
            new_count = baseline + boost
        else:
            new_count = int(current) + boost
        cur.execute(f"UPDATE listings SET view_count = {p} WHERE id = {p}", (new_count, listing_id))
        if not DATABASE_URL:
            conn.commit()
        conn.close()
        return jsonify({"status": "success", "view_count": new_count})
    except Exception as e:
        logger.error(f"view booster error: {e}")
        return jsonify({"status": "error"}), 500


@web_app.route('/api/items/<int:listing_id>/status', methods=['PATCH'])
def api_update_item_status(listing_id):
    """
    Mark listing as sold / rented / pending (re-activate).
    Only the owner (user_chat_id) or ADMIN may update.
    Body: { "status": "sold"|"rented"|"pending", "user_id": <telegram_id> }
    """
    try:
        data = request.json or {}
        new_status = str(data.get('status', '')).lower().strip()
        user_id = data.get('user_id')
        if new_status not in ('sold', 'rented', 'pending', 'expired'):
            return jsonify({"status": "error", "message": "Invalid status"}), 400

        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        cur.execute(f"SELECT user_chat_id, status FROM listings WHERE id = {p}", (listing_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({"status": "error", "message": "Not found"}), 404

        owner_id = row['user_chat_id'] if isinstance(row, dict) else row[0]
        is_admin = (str(user_id) == str(ADMIN_CHAT_ID_INT) and ADMIN_CHAT_ID_INT != 0)
        is_owner = (str(user_id) == str(owner_id))
        if not (is_owner or is_admin):
            conn.close()
            return jsonify({"status": "error", "message": "Forbidden"}), 403

        cur.execute(f"UPDATE listings SET status = {p} WHERE id = {p}", (new_status, listing_id))
        if not DATABASE_URL:
            conn.commit()
        conn.close()
        logger.info(f"✅ Listing #{listing_id} status → {new_status} by user {user_id}")
        return jsonify({"status": "success", "new_status": new_status})
    except Exception as e:
        logger.error(f"status update error: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@web_app.route('/api/items/<int:listing_id>', methods=['DELETE'])
def api_delete_item(listing_id):
    """Soft-delete a listing (status='deleted'). Owner or Admin only."""
    try:
        data = request.json or {}
        user_id = data.get('user_id')
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        cur.execute(f"SELECT user_chat_id FROM listings WHERE id = {p}", (listing_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({"status": "error", "message": "Not found"}), 404
        owner_id = row['user_chat_id'] if isinstance(row, dict) else row[0]
        is_admin = (str(user_id) == str(ADMIN_CHAT_ID_INT) and ADMIN_CHAT_ID_INT != 0)
        is_owner = (str(user_id) == str(owner_id))
        if not (is_owner or is_admin):
            conn.close()
            return jsonify({"status": "error", "message": "Forbidden"}), 403
        cur.execute(f"UPDATE listings SET status = 'deleted' WHERE id = {p}", (listing_id,))
        if not DATABASE_URL:
            conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        logger.error(f"delete item error: {e}")
        return jsonify({"status": "error"}), 500


# ---------- Auto-Expiry / Cleanup Job ----------
def expire_old_listings(days: int = 30) -> int:
    """
    Mark listings older than `days` as 'expired' if they are still active (pending).
    Safe: only touches status, never deletes rows.
    Returns number of rows updated.
    """
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if DATABASE_URL:
            # PostgreSQL
            cur.execute("""
                UPDATE listings
                SET status = 'expired'
                WHERE status = 'pending'
                  AND created_at < (NOW() - INTERVAL '%s days')
            """ % int(days))
            # rowcount available on cursor
            count = cur.rowcount
        else:
            # SQLite
            cur.execute("""
                UPDATE listings
                SET status = 'expired'
                WHERE status = 'pending'
                  AND created_at < datetime('now', ?)
            """, (f'-{int(days)} days',))
            count = cur.rowcount
            conn.commit()
        logger.info(f"🧹 Auto-expiry: {count} listings marked expired (>{days} days)")
        return count or 0
    except Exception as e:
        logger.error(f"expire_old_listings error: {e}", exc_info=True)
        return 0
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def start_cleanup_scheduler():
    """
    Background thread that runs expire_old_listings once per day.
    No external dependency (APScheduler optional). Uses simple sleep loop.
    """
    import time
    def _loop():
        # Run once shortly after boot, then every 24h
        time.sleep(60)
        while True:
            try:
                expire_old_listings(30)
            except Exception as e:
                logger.error(f"cleanup loop error: {e}")
            time.sleep(24 * 3600)
    t = threading.Thread(target=_loop, daemon=True, name="adika-cleanup")
    t.start()
    logger.info("🧹 Cleanup scheduler started (every 24h, 30-day expiry)")


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
                    view_count INTEGER DEFAULT 0,
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
                    view_count INTEGER DEFAULT 0,
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
                cursor.execute("ALTER TABLE listings ADD COLUMN IF NOT EXISTS extra_data JSONB DEFAULT '{}';")
                cursor.execute("ALTER TABLE listings ADD COLUMN IF NOT EXISTS view_count INTEGER DEFAULT 0;")
            else:
                try:
                    cursor.execute("ALTER TABLE listings ADD COLUMN extra_data TEXT DEFAULT '{}';")
                except:
                    pass
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
        import random as _rnd
        baseline_views = _rnd.randint(35, 90)  # social-proof baseline
        query = f"""
            INSERT INTO listings 
            (user_chat_id, user_name, req_type, main_category, sub_category, 
             action_type, property_type, description, price, phone, photo_id, extra_data, status, view_count)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, 'pending', {p})
        """
        params = (
            user_chat_id, user_name, req_type, main_category, 
            sub_category, action_type, property_type, 
            description, price, phone, photo_id,
            extra_json, baseline_views
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

def get_listings_by_category(limit=10, offset=0, req_type=None):
    return get_listings_by_category_ordered(limit=limit, offset=offset, req_type=req_type, order="DESC")

def get_listings_by_category_ordered(limit=20, offset=0, req_type=None, order="DESC"):
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

def get_public_marketplace_items(limit: int = 20, offset: int = 0):
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
                ORDER BY created_at DESC NULLS LAST
                LIMIT %s OFFSET %s
            """, (limit, offset))
            rows = cur.fetchall()
            result = [dict(row) for row in rows]
        else:
            cur.execute("""
                SELECT * FROM listings 
                WHERE UPPER(req_type) = 'SELL'
                  AND status != 'deleted'
                ORDER BY created_at DESC
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

def get_matching_alerts(main_category: str, price: str) -> list:
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


# ==============================================================================
# 5. CONSTANTS & KEYBOARDS
# ==============================================================================

MAIN_KEYBOARD = [
   ["🔍 ለመግዛት / ለመከራየት", "📢 ለመሸጥ / ለማከራየት"],
   ["🛒 የገበያ ቦታ", "📋 የፈላጊዎች ጥያቄዎች"],
   ["👥 የደላሎች መድረክ", "✍️ የደላላ/አቅራቢ መመዝገቢያ"],
   ["⚙️ የማሳወቂያ ማስተካከያ", "📞 እገዛ / Support"],
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
# 6. HELPER FUNCTIONS (SINGLE DEFINITIONS ONLY)
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

def validate_contact(contact: str) -> bool:
    if not contact:
        return False
    contact = contact.strip()
    if contact.startswith('@'):
        username = contact[1:]
        if re.match(r'^[a-zA-Z][a-zA-Z0-9_]{4,31}$', username):
            return True
        return False
    return validate_phone(contact)

def validate_price(price: str) -> bool:
    price = price.replace(',', '').replace(' ', '')
    return price.isdigit()

def clean_description(desc: str, max_len: int = 60) -> str:
    if not desc:
        return ""
    junk = [
        'ዋጋ:', 'ስልክ:', 'አዲስ የሽያጭ', 'WebApp', 'አስቸኳይ ሽያጭ', 'መግለጫ:',
        '📝', '💰', '📞', '⚡', '📢', '🔄', '📦', 'NEW', 'እዱስ',
        '🔥 ለሽያጭ', '🔥 አሸጋጭ', 'የገበያ ቦታ', 'ለሽያጭ', 'ለኪራይ',
        'አይነት:', 'ምድብ:', 'ሁኔታ:', 'ነዳጅ:', 'ማርሽ:', 'ኪሎሜትር:',
        'መሸጥ', 'ማከራየት', 'መግዛት', 'መከራየት',
        '🚗', '🏠', '✨', '🔍', '🛏️', '🛁', '⛽', '⚙️', '🛣️', '📊',
        '🏡', '🏢', '🚚', '🚜', '✅', '❌', '⭐', '👤', '📍', '📛',
        '🎯', '🔔', '🛍️', '🔑', '📌', '💡', '🎉', '⏳', '⛔'
    ]
    clean = desc
    for j in junk:
        clean = clean.replace(j, '')
    clean = ' '.join(line.strip() for line in clean.splitlines() if line.strip())
    clean = ' '.join(clean.split())
    if len(clean) > max_len:
        clean = clean[:max_len] + "..."
    return clean.strip()

def relative_time_am(created_at) -> str:
    """Human-readable relative time in Amharic."""
    if not created_at:
        return ""
    try:
        if isinstance(created_at, str):
            # Handle ISO / SQLite formats
            for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
                try:
                    created_at = datetime.strptime(created_at[:26].replace("T", " "), fmt if "T" not in created_at else fmt)
                    break
                except ValueError:
                    continue
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(str(created_at).replace("Z", ""))
                except Exception:
                    return str(created_at)[:16]
        now = datetime.utcnow()
        # If timezone-aware, compare naively
        if hasattr(created_at, "tzinfo") and created_at.tzinfo:
            created_at = created_at.replace(tzinfo=None)
        delta = now - created_at
        secs = int(delta.total_seconds())
        if secs < 0:
            secs = 0
        if secs < 60:
            return "አሁን"
        if secs < 3600:
            return f"ከ {secs // 60} ደቂቃ በፊት"
        if secs < 86400:
            return f"ከ {secs // 3600} ሰዓት በፊት"
        if secs < 172800:
            return f"ትላንት {created_at.strftime('%H:%M')}"
        if secs < 604800:
            return f"ከ {secs // 86400} ቀን በፊት"
        return created_at.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def format_marketplace_card_professional(item: dict) -> str:
    """Text-mode card for Seller Listings and Buyer Requests."""
    item_id = item.get('id', 'N/A')
    main_cat = item.get('main_category', '')
    sub_cat = (item.get('sub_category') or '').strip()
    price = item.get('price', '-')
    phone = item.get('phone', '-')
    action = item.get('action_type', '')
    req_type = str(item.get('req_type', '')).upper()
    status = str(item.get('status', 'pending')).lower()
    views = item.get('view_count') or 0

    extra = item.get('extra_data', {})
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}

    # --- Header badge ---
    if req_type == "BUY":
        header = f"[🎯 ፈላጊ]  <code>#ADK-{item_id}</code>"
        price_label = "በጀት"
        price_display = f"💰 <b>{price_label}:</b> {extra.get('budget_range') or price or '—'} ብር"
    else:
        if status in ('sold', 'rented'):
            header = f"[🔴 ተሸጧል]  <code>#ADK-{item_id}</code>"
        else:
            header = f"[🟢 ይገኛል]  <code>#ADK-{item_id}</code>"
        negotiable = "የሚደራደር" if extra.get('negotiable', True) else "የማይደራደር"
        urgent = " ⚡ አስቸኳይ" if extra.get('urgent_sale') else ""
        price_display = f"💰 <b>ዋጋ:</b> {price} ብር <i>({negotiable})</i>{urgent}"

    title_display = main_cat or "ንብረት"
    if sub_cat:
        clean_sub = sub_cat.replace('🚗', '').replace('🚚', '').replace('🚜', '').strip()
        if clean_sub:
            title_display += f" ({clean_sub})"

    details = []
    if main_cat in ["መኪና", "car", "CAR"]:
        if extra.get('condition'): details.append(f"├ ሁኔታ: {extra['condition']}")
        if extra.get('fuel_type'): details.append(f"├ ነዳጅ: {extra['fuel_type']}")
        if extra.get('transmission'): details.append(f"├ ማርሽ: {extra['transmission']}")
        if extra.get('mileage'): details.append(f"├ ኪሎሜትር: {extra['mileage']} KM")
        if extra.get('car_type'):
            ct = str(extra['car_type']).replace('🚗', '').replace('🚚', '').replace('🚜', '').strip()
            if ct: details.append(f"├ አይነት: {ct}")
    else:
        if extra.get('condition'): details.append(f"├ ሁኔታ: {extra['condition']}")
        if extra.get('bedrooms'): details.append(f"├ መኝታ: {extra['bedrooms']}")
        if extra.get('bathrooms'): details.append(f"├ መታጠቢያ: {extra['bathrooms']}")
        if extra.get('parking'): details.append(f"├ ፓርኪንግ: {extra['parking']}")
        if extra.get('house_type'):
            ht = str(extra['house_type']).replace('🏠', '').replace('🏢', '').replace('🏡', '').strip()
            if ht: details.append(f"├ አይነት: {ht}")

    rel = relative_time_am(item.get('created_at'))
    lines = [
        header,
        "━━━━━━━━━━━━━━━━━━━━━",
        f"📌 <b>{title_display}</b>",
        price_display,
    ]
    if details:
        lines.append("")
        lines.append("⚙️ ዝርዝር")
        lines.extend(details)

    desc = clean_description(item.get('description', ''), 60)
    if desc:
        lines.append("")
        lines.append(f"📝 {desc}")

    lines.append("━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"👁️ <b>{views}</b> እይታዎች" + (f"  •  🕐 {rel}" if rel else ""))
    lines.append(f"📞 <code>{phone}</code>")
    return "\n".join(lines)


def format_seller_card(item: dict) -> str:
    return format_marketplace_card_professional(item)

def format_buyer_card(req: dict) -> str:
    return format_marketplace_card_professional(req)

def format_broker_profile_professional(b: dict) -> str:
    rating = float(b.get('rating', 5))
    stars = "⭐" * int(rating)
    return (
        "👤 <b>BROKER PROFILE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📛 <b>ስም:</b> {b.get('full_name')}\n"
        f"🎯 <b>ሚና:</b> {b.get('role_type')}\n"
        f"📍 <b>ክፍለ ከተማ:</b> {b.get('sub_city')}\n"
        f"📞 <b>ስልክ:</b> <code>{b.get('phone')}</code>\n"
        f"⭐ <b>ደረጃ:</b> {rating}/5.0 {stars}\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )

def get_nav_buttons(back_callback: str = None) -> list:
    buttons = []
    if back_callback:
        buttons.append(InlineKeyboardButton("⬅️ ተመለስ", callback_data=back_callback))
    buttons.append(InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home"))
    return buttons

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

def build_marketplace_keyboard_clean(item_id: int, owner_id: int, current_user_id: int) -> InlineKeyboardMarkup:
    return build_seller_card_keyboard(item_id, owner_id, current_user_id)

def build_request_keyboard_clean(req_id: int, buyer_id: int) -> InlineKeyboardMarkup:
    return build_request_keyboard(req_id, buyer_id)

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
                
                if photos and len(photos) > 0:
                    try:
                        await bot.send_photo(
                            chat_id=b_id,
                            photo=photos[0],
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
       [InlineKeyboardButton("✅ አዎ - ማሳወቂያ ይድረሰኝ", callback_data="alert_yes")],
       [InlineKeyboardButton("❌ አይ - አያስፈልገኝም", callback_data="alert_no")],
       [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
   ]
   await update.message.reply_text(
       "🔔 **ተመሳሳይ ንብረት ሲለቀቅ ማሳወቂያ እንዲደርስዎት ይፈልጋሉ?**",
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
           notification_text = format_marketplace_card_professional({
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
           })
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
    
    clean_description_text = clean_description(description, 100)
    
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
            
            notification_text = format_marketplace_card_professional(listing_data)
            
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
# 11. BROKER REGISTRATION
# ==============================================================================

async def broker_reg_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    keyboard = [
        [InlineKeyboardButton("👨💼 ደላላ", callback_data="role_broker")],
        [InlineKeyboardButton("🚢 አስመጪ / አቅራቢ", callback_data="role_importer")],
        [InlineKeyboardButton("👤 ባለቤት / አቅራቢ", callback_data="role_owner")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    await update.message.reply_text(
        "📝 **የምዝገባ አይነት ይምረጡ፦**\n\n"
        "💡 *ማብራሪያ፦*\n"
        "• ደላላ - ሽያጭ/ኪራይ የሚያመቻች\n"
        "• አስመጪ/አቅራቢ - ከውጭ የሚያስገባ\n"
        "• ባለቤት/አቅራቢ - ንብረት ያለው",
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
        "role_broker": "ደላላ",
        "role_importer": "አስመጪ/አቅራቢ",
        "role_owner": "ባለቤት/አቅራቢ"
    }
    role = role_map.get(query.data, "አቅራቢ")
    context.user_data['broker_role'] = role
    await query.edit_message_text(
        f"👤 **ምዝገባ፦ {role}**\n\n1️⃣ ሙሉ ስምዎን ያስገቡ፦",
        parse_mode="Markdown"
    )
    return BROKER_NAME

async def broker_reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['broker_name'] = update.message.text
    await update.message.reply_text("2️⃣ **የስልክ ቁጥርዎን ያስገቡ፦**", parse_mode="Markdown")
    return BROKER_PHONE

async def broker_reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    if not validate_phone(update.message.text):
        await update.message.reply_text("❌ ትክክለኛ የስልክ ቁጥር ያስገቡ። (ለምሳሌ፦ 0911223344)")
        return BROKER_PHONE
    context.user_data['broker_phone'] = update.message.text
    keyboard = [[InlineKeyboardButton(sc, callback_data=f"broker_sc_{sc}")] for sc in SUB_CITIES]
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    await update.message.reply_text(
        "3️⃣ **የሚሰሩበትን ክፍለ ከተማ ይምረጡ፦**",
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
        "4️⃣ **የፋይዳ (National ID) ወይም የነዋሪነት መታወቂያ ፎቶ ያንሱና ይላኩ፦**\n\n"
        "💡 *ይህ ለማረጋገጫ ብቻ ነው*",
        parse_mode="Markdown"
    )
    return BROKER_NID_PHOTO

async def broker_reg_nid_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    user = update.effective_user
    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    if not photo_id:
        await update.message.reply_text("❌ እባክዎ የመታወቂያ ፎቶ ይላኩ።")
        return BROKER_NID_PHOTO
    role = context.user_data.get('broker_role', 'አቅራቢ')
    name = context.user_data.get('broker_name', user.first_name)
    phone = context.user_data.get('broker_phone', '')
    sub_city = context.user_data.get('broker_subcity', '')
    broker_id = add_broker(user.id, name, phone, role, photo_id, sub_city)
    if broker_id:
        await update.message.reply_text(
            "✅ **ምዝገባዎ በስኬት ተጠናቋል!** 🎉\n\n"
            "⏳ አድሚኑ መረጃዎን ካረጋገጠ በኋላ ማስታወቂያ ይደርስዎታል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
        if ADMIN_CHAT_ID_INT != 0:
            admin_msg = (
                f"🚨 **አዲስ የ{role} ምዝገባ ጥያቄ!**\n\n"
                f"👤 ስም: {name}\n"
                f"🎭 ሚና: {role}\n"
                f"📞 ስልክ: {phone}\n"
                f"📍 ክፍለ ከተማ: {sub_city}\n"
                f"🆔 Telegram ID: `{user.id}`"
            )
            admin_kbd = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ አጽድቅ", callback_data=f"admin_appr_{user.id}"),
                    InlineKeyboardButton("❌ ሰርዝ", callback_data=f"admin_reje_{user.id}")
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
            "❌ **ምዝገባውን ማጠናቀቅ አልተቻለም!** እባክዎ እንደገና ይሞክሩ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
    context.user_data.clear()
    return ConversationHandler.END


# ==============================================================================
# 12. BROKER OFFER FLOW
# ==============================================================================

async def broker_have_item_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    broker = get_broker(user_id)
    if not broker or broker.get('status') != 'approved':
        await query.message.reply_text(
            "⛔ **ይህን ማድረግ የሚችሉት በአድሚን የተረጋገጡ ደላሎች/አቅራቢዎች ብቻ ናቸው!**",
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    parts = query.data.split('_')
    if len(parts) < 3:
        await query.message.reply_text("❌ የተሳሳተ መረጃ ተላኳል።")
        return ConversationHandler.END
    req_id = parts[2]
    buyer_id = parts[3] if len(parts) >= 4 else None
    if not buyer_id:
        listing = get_listing_by_id(int(req_id)) if req_id.isdigit() else None
        if listing:
            buyer_id = listing.get('user_chat_id')
    if not buyer_id:
        await query.message.reply_text("❌ የፈላጊው መረጃ አልተገኘም።")
        return ConversationHandler.END
    context.user_data['target_req_id'] = req_id
    context.user_data['target_buyer_id'] = buyer_id
    await query.message.reply_text(
        f"✅ **ጥያቄ #ADK-{req_id}**\n\n"
        f"✍️ **ያለዎትን ንብረት ዝርዝር መረጃ እና ዋጋ ያስገቡ፦**\n\n"
        f"💡 *ምሳሌ፦* ቶዮታ ቪትዝ 2021፣ 30,000 KM፣ ዋጋ 2.4 ሚሊዮን",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True),
        parse_mode="Markdown"
    )
    return BROKER_OFFER_TEXT

async def broker_offer_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['offer_text'] = text
    await update.message.reply_text(
        "📸 **የንብረቱን ፎቶ ይላኩ፦**\n\n"
        "(ፎቶ ከሌልዎት `ፎቶ የለውም` ብለው ይጻፉ)",
        reply_markup=ReplyKeyboardMarkup([["ፎቶ የለውም"], ["🏠 ዋና ገጽ"]], resize_keyboard=True),
        parse_mode="Markdown"
    )
    return BROKER_OFFER_PHOTO

async def broker_offer_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    raw_buyer_id = context.user_data.get('target_buyer_id')
    req_id = context.user_data.get('target_req_id')
    offer_text = context.user_data.get('offer_text')
    
    if not raw_buyer_id or not req_id or not offer_text:
        await update.message.reply_text(
            "❌ <b>የሂደት ስህተት ተከሰቷል</b>",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="HTML"
        )
        return ConversationHandler.END
    
    buyer_id = int(raw_buyer_id)
    broker_user = update.effective_user
    broker = get_broker(broker_user.id)
    broker_name = broker.get('full_name') if broker else (broker_user.first_name or "ደላላ")
    broker_phone = broker.get('phone', 'አልተጠቀሰም') if broker else 'አልተጠቀሰም'
    
    message_to_buyer = (
        f"🎉 <b>አዲስ አማራጭ ተገኝቷል!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>ጥያቄ፡</b> <code>#ADK-{req_id}</code>\n"
        f"👤 <b>አቅራቢ፡</b> {broker_name}\n"
        f"📞 <b>ስልክ፡</b> <code>{broker_phone}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 <b>የንብረቱ ዝርዝር፡</b>\n{offer_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 ለበለጠ መረጃ ይደውሉ"
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
                parse_mode="HTML"
            )
        else:
            await context.bot.send_message(
                chat_id=buyer_id,
                text=message_to_buyer,
                parse_mode="HTML"
            )
        
        await update.message.reply_text(
            "✅ <b>መረጃዎ ለፈላጊው ተልኳል!</b>",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Failed to send offer: {e}")
        await update.message.reply_text(
            "❌ <b>መረጃውን መላክ አልተቻለም</b>",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="HTML"
        )
    
    context.user_data.clear()
    return ConversationHandler.END

async def have_buyer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    broker = get_broker(user_id)
    if not broker or broker.get('status') != 'approved':
        await query.answer("⛔ የተረጋገጡ ደላሎች ብቻ ነው!", show_alert=True)
        return
    await query.answer()
    parts = query.data.split('_')
    if len(parts) < 3:
        await query.answer("❌ የተሳሳተ መረጃ", show_alert=True)
        return
    item_id = parts[2]
    owner_id = parts[3] if len(parts) >= 4 else None
    listing = get_listing_by_id(int(item_id)) if str(item_id).isdigit() else None
    if not listing:
        await query.answer("❌ ማስታወቂያው አልተገኘም", show_alert=True)
        return
    phone = listing.get('phone', 'አልተገኘም')
    owner_name = listing.get('user_name', 'ባለቤት')
    text = (
        f"🤝 **ገዢ/ተከራይ አለዎት**\n\n"
        f"📦 ማስታወቂያ: `#ADK-{item_id}`\n"
        f"👤 ባለቤት: {owner_name}\n"
        f"📞 ስልክ: `{phone}`\n\n"
        f"💡 በቀጥታ ደውለው መገበያየት ይችላሉ።"
    )
    try:
        await query.edit_message_text(text=text, parse_mode="Markdown")
    except Exception:
        try:
            await query.edit_message_caption(caption=text, parse_mode="Markdown")
        except Exception:
            await context.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")

async def want_myself_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split('_')
    item_id = parts[2] if len(parts) >= 3 else "?"
    listing = get_listing_by_id(int(item_id)) if str(item_id).isdigit() else None
    phone = listing.get('phone', 'አልተገኘም') if listing else 'አልተገኘም'
    text = (
        f"👤 **ለራስዎ ይፈልጋሉ**\n\n"
        f"📦 ማስታወቂያ: `#ADK-{item_id}`\n"
        f"📞 የባለቤቱ ስልክ: `{phone}`\n\n"
        f"💡 በቀጥታ ደውለው መገበያየት ይችላሉ።"
    )
    try:
        await query.edit_message_text(text=text, parse_mode="Markdown")
    except Exception:
        try:
            await query.edit_message_caption(caption=text, parse_mode="Markdown")
        except Exception:
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=text,
                parse_mode="Markdown"
            )


# ==============================================================================
# 13. VIEW REQUESTS / MARKETPLACE / DIRECTORY
# ==============================================================================

# ---------- Hybrid choice: Web App vs Text Mode ----------

TEXT_PAGE_SIZE = 4  # items per text-mode page (good for slow networks)


async def marketplace_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show hybrid choice for Marketplace (Web App vs Text)."""
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "adika-vrkk.onrender.com")
    web_url = f"https://{hostname}/explorer"
    keyboard = [
        [InlineKeyboardButton(
            "🌐 በዌብ አፕ ክፈት (ሙሉ ፎቶዎች)",
            web_app=WebAppInfo(url=web_url)
        )],
        [InlineKeyboardButton(
            "⚡ በጽሁፍ እይ (ለዝቅተኛ ኔትወርክ)",
            callback_data="text_mode_marketplace_1"
        )],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")],
    ]
    await update.message.reply_text(
        "🛍️ <b>የገበያ ቦታ</b>\n\n"
        "እባክዎን የማሳያ መንገድ ይምረጡ፦\n\n"
        "🌐 <b>ዌብ አፕ</b> — ሙሉ ፎቶዎች፣ ፈጣን ፍለጋ እና ማጣሪያ\n"
        "⚡ <b>ጽሁፍ</b> — ለዝቅተኛ ኔትወርክ (ቀላል ጽሁፍ + ገጽ በገጽ)",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


async def requests_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show hybrid choice for Buyer Requests. Restricted to approved brokers + admin."""
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_CHAT_ID_INT)
    broker = get_broker(user_id)

    if not is_admin and not broker:
        await update.message.reply_text(
            "⛔ <b>ይህን ማየት የሚችሉት የተረጋገጡ ደላሎች ብቻ ናቸው!</b>",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="HTML"
        )
        return
    if not is_admin and broker.get('status') != 'approved':
        await update.message.reply_text(
            "⏳ <b>ምዝገባዎ ገና አልጸደቀም</b>",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="HTML"
        )
        return

    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "adika-vrkk.onrender.com")
    # Explorer opens on Requests tab via query param (frontend can read it)
    web_url = f"https://{hostname}/explorer?tab=requests"
    keyboard = [
        [InlineKeyboardButton(
            "🌐 በዌብ አፕ ክፈት (ሙሉ ፎቶዎች)",
            web_app=WebAppInfo(url=web_url)
        )],
        [InlineKeyboardButton(
            "⚡ በጽሁፍ እይ (ለዝቅተኛ ኔትወርክ)",
            callback_data="text_mode_requests_1"
        )],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")],
    ]
    await update.message.reply_text(
        "📋 <b>የፈላጊዎች ዝርዝር</b>\n\n"
        "እባክዎን የማሳያ መንገድ ይምረጡ፦\n\n"
        "🌐 <b>ዌብ አፕ</b> — ሙሉ መረጃ + ፎቶዎች\n"
        "⚡ <b>ጽሁፍ</b> — ለዝቅተኛ ኔትወርክ (ቀላል ጽሁፍ + ገጽ በገጽ)",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


def _build_single_card_keyboard(
    mode: str,
    item: dict,
    viewer_id: int = 0,
    page: int = 1,
    total_pages: int = 1,
    show_pagination: bool = False,
) -> InlineKeyboardMarkup:
    """
    ONE clean keyboard per card — no duplication.
      Row 1: [📞 ደውል] [💬 ቻት]   (or [📩 አነጋግር] for requests)
      Row 2: [✅ ተሸጧል ብለህ መዝግብ]  (owner/admin only, marketplace)
      Row 3: [◀️ ቀዳሚ] [1/N] [ቀጣይ ▶️]  (only on last card of page)
      Row 4: [🏠 ዋና ገጽ]           (only on last card of page)
    """
    rows = []
    item_id = item.get('id')
    owner_id = item.get('user_chat_id')
    phone = (item.get('phone') or '').strip()
    status = str(item.get('status', '')).lower()
    extra = item.get('extra_data') or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}
    tg_user = (extra.get('telegram_user') or '').strip().lstrip('@')

    is_owner = bool(viewer_id and owner_id and int(viewer_id) == int(owner_id))
    is_admin = bool(viewer_id and ADMIN_CHAT_ID_INT and int(viewer_id) == int(ADMIN_CHAT_ID_INT))
    inactive = status in ('sold', 'rented', 'deleted', 'expired')

    # Row 1 — contact actions (single row, built once)
    contact_row = []
    if mode == "marketplace":
        if phone and not inactive:
            contact_row.append(InlineKeyboardButton("📞 ደውል", callback_data=f"tm_call_{item_id}"))
        if tg_user and not inactive:
            contact_row.append(InlineKeyboardButton("💬 ቻት", url=f"https://t.me/{tg_user}"))
    else:
        if phone:
            contact_row.append(InlineKeyboardButton("📩 አነጋግር", callback_data=f"tm_call_{item_id}"))
        if tg_user:
            contact_row.append(InlineKeyboardButton("💬 ቻት", url=f"https://t.me/{tg_user}"))
    if contact_row:
        rows.append(contact_row)

    # Row 2 — owner mark-sold (marketplace only, once)
    if mode == "marketplace" and (is_owner or is_admin) and not inactive:
        rows.append([
            InlineKeyboardButton("✅ ተሸጧል ብለህ መዝግብ", callback_data=f"tm_sold_{item_id}")
        ])

    # Row 3+4 — pagination + home only on the last card of the page
    if show_pagination:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("◀️ ቀዳሚ", callback_data=f"text_mode_{mode}_{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("ቀጣይ ▶️", callback_data=f"text_mode_{mode}_{page + 1}"))
        if nav:
            rows.append(nav)
        rows.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])

    return InlineKeyboardMarkup(rows)


def _increment_views_batch(item_ids: list, amount: int = 13) -> dict:
    """Increment view_count by `amount` for each listing id. Returns {id: new_count}."""
    result = {}
    if not item_ids:
        return result
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        for lid in item_ids:
            try:
                cur.execute(
                    f"UPDATE listings SET view_count = COALESCE(view_count, 0) + {int(amount)} WHERE id = {p}",
                    (lid,),
                )
                cur.execute(f"SELECT view_count FROM listings WHERE id = {p}", (lid,))
                row = cur.fetchone()
                if row is not None:
                    result[lid] = row['view_count'] if isinstance(row, dict) else row[0]
            except Exception as e:
                logger.warning(f"view increment failed for {lid}: {e}")
        if not DATABASE_URL:
            conn.commit()
    except Exception as e:
        logger.error(f"_increment_views_batch error: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    return result


async def text_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Text-mode listings/requests — ONE message per card (no button duplication).
    Newest posts at BOTTOM (ORDER BY created_at ASC).
    callback_data: text_mode_marketplace_1 | text_mode_requests_2 | tm_sold_N | tm_call_N
    """
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data == "noop":
        return

    user_id = query.from_user.id
    chat_id = query.message.chat_id if query.message else user_id

    # --- Owner: mark as sold ---
    if data.startswith("tm_sold_"):
        try:
            listing_id = int(data.replace("tm_sold_", ""))
        except ValueError:
            return
        listing = get_listing_by_id(listing_id)
        if not listing:
            await query.answer("ማስታወቂያ አልተገኘም", show_alert=True)
            return
        owner_id = listing.get('user_chat_id')
        is_admin = (user_id == ADMIN_CHAT_ID_INT and ADMIN_CHAT_ID_INT != 0)
        if int(owner_id or 0) != int(user_id) and not is_admin:
            await query.answer("⛔ የባለቤት ብቻ ነው!", show_alert=True)
            return
        if update_listing_status(listing_id, "sold"):
            await query.answer("✅ እንደተሸጠ ተመዝግቧል!", show_alert=True)
            try:
                # Update badge on this message only
                listing['status'] = 'sold'
                card = format_marketplace_card_professional(listing)
                await query.edit_message_text(
                    text=card,
                    parse_mode="HTML",
                    reply_markup=_build_single_card_keyboard(
                        "marketplace", listing, viewer_id=user_id, show_pagination=False
                    ),
                    disable_web_page_preview=True,
                )
            except Exception:
                pass
        else:
            await query.answer("ስህተት ተከስቷል", show_alert=True)
        return

    # --- Show phone ---
    if data.startswith("tm_call_"):
        try:
            listing_id = int(data.replace("tm_call_", ""))
        except ValueError:
            return
        listing = get_listing_by_id(listing_id)
        phone = (listing or {}).get('phone') or 'አልተገኘም'
        await query.answer(f"📞 {phone}", show_alert=True)
        return

    # Parse page navigation
    parts = data.split("_")
    if len(parts) < 4 or parts[0] != "text" or parts[1] != "mode":
        return
    mode = parts[2]
    try:
        page = max(1, int(parts[3]))
    except (ValueError, IndexError):
        page = 1

    is_admin = (user_id == ADMIN_CHAT_ID_INT)
    if mode == "requests":
        broker = get_broker(user_id)
        if not is_admin and (not broker or broker.get('status') != 'approved'):
            await query.edit_message_text(
                "⛔ ይህን ማየት የሚችሉት የተረጋገጡ ደላሎች ብቻ ናቸው!",
                parse_mode="HTML",
            )
            return

    try:
        # ASC = oldest first, newest at BOTTOM (Telegram reading flow)
        if mode == "marketplace":
            total = count_listings(req_type="SELL")
            items = get_listings_by_category_ordered(
                limit=TEXT_PAGE_SIZE,
                offset=(page - 1) * TEXT_PAGE_SIZE,
                req_type="SELL",
                order="ASC",
            )
            title = "🛒 <b>የገበያ ቦታ</b> (ጽሁፍ)"
            empty_msg = "📭 ምንም የሚሸጡ ንብረቶች የሉም።"
        else:
            total = count_listings(req_type="BUY")
            items = get_listings_by_category_ordered(
                limit=TEXT_PAGE_SIZE,
                offset=(page - 1) * TEXT_PAGE_SIZE,
                req_type="BUY",
                order="ASC",
            )
            title = "📋 <b>የፈላጊዎች ጥያቄዎች</b> (ጽሁፍ)"
            empty_msg = "📭 ምንም ንቁ ጥያቄዎች የሉም።"

        if not items:
            await query.edit_message_text(
                empty_msg,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")
                ]]),
            )
            return

        # +13 views per rendered card
        ids = [it.get('id') for it in items if it.get('id')]
        new_counts = _increment_views_batch(ids, amount=13)
        for it in items:
            if it.get('id') in new_counts:
                it['view_count'] = new_counts[it['id']]

        total_pages = max(1, (total + TEXT_PAGE_SIZE - 1) // TEXT_PAGE_SIZE)
        page = min(page, total_pages)

        # Replace the choice message with a page header
        try:
            await query.edit_message_text(
                f"{title}\n📄 ገጽ <b>{page}/{total_pages}</b>  •  ጠቅላላ <b>{total}</b>",
                parse_mode="HTML",
            )
        except Exception:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"{title}\n📄 ገጽ <b>{page}/{total_pages}</b>  •  ጠቅላላ <b>{total}</b>",
                parse_mode="HTML",
            )

        # ONE message per card → one clean keyboard each (no duplication)
        for idx, it in enumerate(items):
            is_last = (idx == len(items) - 1)
            card_text = format_marketplace_card_professional(it)
            kbd = _build_single_card_keyboard(
                mode=mode,
                item=it,
                viewer_id=user_id,
                page=page,
                total_pages=total_pages,
                show_pagination=is_last,
            )
            await context.bot.send_message(
                chat_id=chat_id,
                text=card_text,
                parse_mode="HTML",
                reply_markup=kbd,
                disable_web_page_preview=True,
            )

    except Exception as e:
        logger.error(f"text_mode_callback error: {e}", exc_info=True)
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ መረጃ ማምጣት አልተቻለም። እባክዎ እንደገና ይሞክሩ።",
                parse_mode="HTML",
            )
        except Exception:
            pass


# Keep old full-photo chat view available if needed later
async def view_public_marketplace_clean(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = get_public_marketplace_items(limit=15)
    user_id = update.effective_user.id
    if not items:
        await update.message.reply_text(
            "📭 ምንም ንብረቶች የሉም",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return
    await update.message.reply_text(
        f"🛍️ <b>{len(items)} ንብረቶች ተገኝተዋል</b>",
        parse_mode="HTML"
    )
    for item in items:
        photos = item.get('photos') or ([item['photo_id']] if item.get('photo_id') else [])
        card_text = format_marketplace_card_professional(item)
        reply_markup = build_marketplace_keyboard_clean(
            item_id=item.get('id'),
            owner_id=item.get('user_chat_id'),
            current_user_id=user_id
        )
        if photos:
            try:
                await update.message.reply_photo(
                    photo=photos[0], caption=card_text,
                    reply_markup=reply_markup, parse_mode="HTML"
                )
            except Exception:
                await update.message.reply_text(card_text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await update.message.reply_text(card_text, reply_markup=reply_markup, parse_mode="HTML")


async def view_requests_clean(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Legacy full list (kept for compatibility). Prefer hybrid via requests_choice."""
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_CHAT_ID_INT)
    broker = get_broker(user_id)
    if not is_admin and not broker:
        await update.message.reply_text(
            "⛔ <b>ይህን ማየት የሚችሉት የተረጋገጡ ደላሎች ብቻ ናቸው!</b>",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="HTML"
        )
        return
    if not is_admin and broker.get('status') != 'approved':
        await update.message.reply_text(
            "⏳ <b>ምዝገባዎ ገና አልጸደቀም</b>",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="HTML"
        )
        return
    listings = get_listings_by_category_ordered(limit=20, offset=0, req_type="BUY", order="DESC")
    total = count_listings(req_type="BUY")
    if not listings:
        await update.message.reply_text(
            "📭 <b>ምንም ንቁ ጥያቄዎች የሉም</b>",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="HTML"
        )
        return
    broker_name = "👑 አድሚን" if is_admin else (broker.get('full_name') if broker else "ደላላ")
    await update.message.reply_text(
        f"📋 <b>የፈላጊዎች ዝርዝር</b>\n━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>{broker_name}</b>\n🔔 <b>ጠቅላላ:</b> {total} ጥያቄዎች",
        parse_mode="HTML"
    )
    for listing in listings:
        card_text = format_marketplace_card_professional(listing)
        reply_markup = build_request_keyboard_clean(
            req_id=listing.get('id'),
            buyer_id=listing.get('user_chat_id')
        )
        try:
            await update.message.reply_text(card_text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Failed to send listing: {e}")


async def view_brokers_directory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(sc, callback_data=f"dir_sc_{sc}")] for sc in SUB_CITIES]
    keyboard.append([InlineKeyboardButton("🌐 የሁሉም ክፍለ ከተሞች", callback_data="dir_sc_ሁሉም")])
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])

    await update.message.reply_text(
        "📍 <b>የደላሎችና አቅራቢዎች ማውጫ</b>\n\n"
        "እባክዎን ማየት የሚፈልጉበትን ክፍለ ከተማ ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

async def filter_brokers_by_subcity_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    sub_city = query.data.replace("dir_sc_", "")
    brokers = get_approved_brokers_directory(sub_city=sub_city)

    if not brokers:
        await query.edit_message_text(
            f"📭 በ{sub_city} ክፍለ ከተማ የተመዘገቡ ደላሎች አልተገኙም።",
            parse_mode="HTML"
        )
        return

    msg = (
        f"📋 <b>የተረጋገጡ ደላሎች ዝርዝር</b>\n"
        f"📍 <b>{sub_city}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    for b in brokers:
        msg += format_broker_profile_professional(b) + "\n\n"

    await query.edit_message_text(msg, parse_mode="HTML")


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
        f"🚗 **መኪና፦** {car_text}\n"
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


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler – log and notify user without crashing the bot."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    # Try to notify the user if possible
    try:
        if update and isinstance(update, Update) and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ ይቅርታ፣ ስህተት ተከስቷል። እባክዎ እንደገና ይሞክሩ ወይም /start ይጫኑ።"
            )
    except Exception as notify_err:
        logger.warning(f"Could not send error message to user: {notify_err}")


def main():
    global bot_app

    init_db()
    threading.Thread(target=run_flask, daemon=True).start()
    start_cleanup_scheduler()  # 30-day auto-expiry background job

    app = Application.builder().token(BOT_TOKEN).build()
    bot_app = app

    cancel_filter = filters.Regex("^🏠 ዋና ገጽ$")
    cancel_handler = MessageHandler(cancel_filter, go_home)

    # Buyer Conversation
    buyer_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 ለመግዛት / ለመከራየት$"), buyer_start)],
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
        entry_points=[MessageHandler(filters.Regex("^📢 ለመሸጥ / ለማከራየት$"), seller_start)],
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
        entry_points=[MessageHandler(filters.Regex("^✍️ የደላላ/አቅራቢ መመዝገቢያ$"), broker_reg_start)],
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

    # Message handlers — Hybrid choice for Marketplace & Requests
    app.add_handler(MessageHandler(filters.Regex("^🛒 የገበያ ቦታ$"), marketplace_choice))
    app.add_handler(MessageHandler(filters.Regex("^📋 የፈላጊዎች ጥያቄዎች$"), requests_choice))
    app.add_handler(MessageHandler(filters.Regex("^👥 የደላሎች መድረክ$"), view_brokers_directory))
    app.add_handler(MessageHandler(filters.Regex("^📞 እገዛ / Support$"), help_command))
    app.add_handler(MessageHandler(filters.Regex("^⚙️ የማሳወቂያ ማስተካከያ$"), notification_prefs_start))
    app.add_handler(cancel_handler)

    # Callback query handlers
    app.add_handler(CallbackQueryHandler(go_home, pattern="^flow_home$"))
    app.add_handler(CallbackQueryHandler(text_mode_callback, pattern=r"^(text_mode_|tm_sold_|tm_call_)"))
    app.add_handler(CallbackQueryHandler(lambda u, c: u.callback_query.answer(), pattern="^noop$"))
    app.add_handler(CallbackQueryHandler(admin_approval_callback, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(delete_request_callback, pattern=r"^delete_req_"))
    app.add_handler(CallbackQueryHandler(nohave_item_callback, pattern="^nohave_item_"))
    app.add_handler(CallbackQueryHandler(filter_brokers_by_subcity_callback, pattern="^dir_sc_"))
    app.add_handler(CallbackQueryHandler(mark_sold_callback, pattern="^mark_sold_"))
    app.add_handler(CallbackQueryHandler(have_buyer_callback, pattern="^have_buyer_"))
    app.add_handler(CallbackQueryHandler(want_myself_callback, pattern="^want_myself_"))
    app.add_handler(CallbackQueryHandler(notification_prefs_callback, pattern="^notif_pref_"))

    app.add_error_handler(error_handler)

    logger.info("🚀 Adika Marketplace Bot በስኬት ተጀምሯል...")
    app.run_polling()


if __name__ == "__main__":
    main()
