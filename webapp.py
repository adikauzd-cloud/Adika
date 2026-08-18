# ==============================================================================
# webapp.py — Flask Mini App + REST API
# ==============================================================================
import json
import os
import asyncio
import random
import threading
from flask import Flask, request, jsonify, Response

from config import (
    logger, PORT, MAX_IMAGE_BYTES, ADMIN_CHAT_ID_INT, DATABASE_URL, WEBAPP_URL,
)
from models import (
    LAST_DB_ERROR,
    get_db_connection, get_placeholder, add_listing, get_listing_by_id,
    update_listing_status, save_search_alert, expire_old_listings,
    get_active_brokers, get_platform_stats, count_listings, count_brokers,
)

# bot_app set from main for notifications
bot_app = None
bot_loop = None  # set from main post_init

web_app = Flask(__name__)

# Telegram Mini Apps + cross-origin API
try:
    from flask_cors import CORS
    CORS(web_app, resources={r"/*": {"origins": "*"}})
except Exception:
    pass

@web_app.after_request
def _telegram_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
    # Allow embedding in Telegram WebView
    resp.headers.pop("X-Frame-Options", None)
    resp.headers.pop("X-Frame-Options", None)  # Telegram needs frames allowed
    resp.headers["Content-Security-Policy"] = "frame-ancestors 'self' https://web.telegram.org https://telegram.org"
    return resp


def _json_safe(obj):
    """Make DB rows JSON-serializable (datetime, Decimal, bytes)."""
    from datetime import date, datetime
    from decimal import Decimal
    if obj is None:
        return None
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (bytes, bytearray)):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    return obj



SELLER_FORM_HTML = r"""
<!DOCTYPE html>
<html lang="am">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <title>ንብረት ለገበያ</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <script src="https://cdn.tailwindcss.com"></script>
  <script crossorigin src="https://cdn.jsdelivr.net/npm/react@18.2.0/umd/react.production.min.js"></script>
  <script crossorigin src="https://cdn.jsdelivr.net/npm/react-dom@18.2.0/umd/react-dom.production.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/@babel/standalone@7.24.0/babel.min.js"></script>

  <style>
    body { margin:0; background:#f8fafc; font-family:system-ui,-apple-system,sans-serif; -webkit-tap-highlight-color:transparent; }
    .chip-active { background:#2563eb; color:#fff; font-weight:700; box-shadow:0 1px 3px rgba(37,99,235,.3); }
    .chip-idle { background:#f3f4f6; color:#4b5563; border:1px solid #e5e7eb; }
    input, textarea, select { font-size: 16px !important; } /* prevent iOS zoom */
  </style>
</head>
<body class="bg-[#E8F3FC]">
  <div id="root"></div>
  <script type="text/babel">
    const { useState, useEffect, useRef } = React;
    const tg = (window.Telegram && window.Telegram.WebApp) ? window.Telegram.WebApp : {
      expand(){}, ready(){}, close(){}, initDataUnsafe: {}, setHeaderColor(){}, setBackgroundColor(){}, showAlert: (m)=>alert(m)
    };
    try { tg.ready(); tg.expand(); } catch (e) { console.warn(e); }
    try { tg.setHeaderColor('#2563eb'); tg.setBackgroundColor('#f8fafc'); } catch (e) {}

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
      const [photoBusy, setPhotoBusy] = useState(false);
      const [photoError, setPhotoError] = useState('');
      const [status, setStatus] = useState('');
      const [submitting, setSubmitting] = useState(false);
      const fileRef = useRef(null);
      const [dragOver, setDragOver] = useState(false);

      const compressImage = (file) => new Promise((resolve, reject) => {
        try {
          if (!file || file.size > 8 * 1024 * 1024) {
            reject(new Error('ፎቶ በጣም ትልቅ ነው (max 8MB)'));
            return;
          }
          const reader = new FileReader();
          reader.onerror = () => reject(new Error('ፎቶ ማንበብ አልተቻለም'));
          reader.onload = (e) => {
            const img = new Image();
            img.onerror = () => reject(new Error('ልክ ያልሆነ ምስል'));
            img.onload = () => {
              try {
                const canvas = document.createElement('canvas');
                let cw = img.width, ch = img.height;
                const max = 1000;
                if (cw > max || ch > max) {
                  if (cw > ch) { ch = (ch / cw) * max; cw = max; }
                  else { cw = (cw / ch) * max; ch = max; }
                }
                canvas.width = cw; canvas.height = ch;
                canvas.getContext('2d').drawImage(img, 0, 0, cw, ch);
                resolve(canvas.toDataURL('image/jpeg', 0.65));
              } catch (err) {
                reject(err);
              }
            };
            img.src = e.target.result;
          };
          reader.readAsDataURL(file);
        } catch (err) {
          reject(err);
        }
      });

      const addFiles = async (fileList) => {
        setPhotoError('');
        const files = Array.from(fileList || []).slice(0, 5 - photos.length);
        if (!files.length) return;
        setPhotoBusy(true);
        try {
          for (const f of files) {
            if (!f.type || !f.type.startsWith('image/')) continue;
            try {
              const dataUrl = await compressImage(f);
              setPhotos(prev => prev.length < 5 ? [...prev, dataUrl] : prev);
            } catch (err) {
              setPhotoError(String(err.message || err));
              try { if (window.Telegram?.WebApp?.showAlert) window.Telegram.WebApp.showAlert(String(err.message || err)); } catch (_) {}
            }
          }
        } finally {
          setPhotoBusy(false);
        }
      };

      const removePhoto = (i) => setPhotos(prev => prev.filter((_, idx) => idx !== i));

      const canNext1 = category && (category === 'መኪና' ? (carType || condition) : (houseType || houseCondition));
      // Step 2: NEVER block on photos; price is soft-required but empty still allows Next
      const canNext2 = true;
      const canSubmit = Boolean(description && description.trim());

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
              <p className="font-bold text-base text-green-700 leading-snug px-2 text-center">ማስታወቂያዎ በተሳካ ሁኔታ ተመዝግቧል! ለደላሎችም ተልኳል። ማስታወቂያዎን ማጥፋት ወይም ማስተካከል ሲፈልጉ በማንኛውም ጊዜ ወደ 'የገበያ ቦታ' በመሄድ ማስተካከል ይችላሉ።</p>
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
                  {photoBusy && <p className="text-[11px] text-blue-600">ፎቶ እየተሰራ ነው…</p>}
                  {photoError && <p className="text-[11px] text-red-600">{photoError}</p>}
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
                  <label className="text-xs font-medium text-gray-600 mb-1.5 block">📞 ስልክ ቁጥር <span className="text-gray-400 font-normal">(አማራጭ)</span></label>
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
              <button type="button" onClick={() => {
                  if (step === 1 && !canNext1) return;
                  if (photoBusy) return;
                  setStep(s => s+1);
                }}
                disabled={step===1 ? !canNext1 : photoBusy}
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

    (function(){
      try {
        if (!window.React || !window.ReactDOM) {
          document.getElementById('root').innerHTML = '<div style="padding:20px;color:#b91c1c;font-family:system-ui">Failed to load React CDN</div>';
          return;
        }
        ReactDOM.createRoot(document.getElementById('root')).render(<SellerForm />);
      } catch (e) {
        document.getElementById('root').innerHTML = '<div style="padding:20px;color:#b91c1c;font-family:system-ui">UI Error: '+e.message+'</div>';
      }
    })();
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
  <script crossorigin src="https://cdn.jsdelivr.net/npm/react@18.2.0/umd/react.production.min.js"></script>
  <script crossorigin src="https://cdn.jsdelivr.net/npm/react-dom@18.2.0/umd/react-dom.production.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/@babel/standalone@7.24.0/babel.min.js"></script>

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
    const tg = (window.Telegram && window.Telegram.WebApp) ? window.Telegram.WebApp : {
      expand(){}, ready(){}, close(){}, initDataUnsafe: {}, setHeaderColor(){}, setBackgroundColor(){}, showAlert: (m)=>alert(m)
    };
    try { tg.ready(); tg.expand(); } catch (e) { console.warn(e); }
    try { tg.setHeaderColor('#2563eb'); tg.setBackgroundColor('#f8fafc'); } catch (e) {}

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
        if (!details || submitting) return;
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
              <p className="font-bold text-base text-green-700 leading-snug px-2 text-center">ማስታወቂያዎ በተሳካ ሁኔታ ተመዝግቧል! ለደላሎችም ተልኳል። ማስታወቂያዎን ማጥፋት ወይም ማስተካከል ሲፈልጉ በማንኛውም ጊዜ ወደ 'የገበያ ቦታ' በመሄድ ማስተካከል ይችላሉ።</p>
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
              <label className="text-xs font-medium text-gray-600 mb-1.5 block">📞 ስልክ ቁጥር <span className="text-gray-400 font-normal">(አማራጭ)</span></label>
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
            <button type="button" onClick={submit} disabled={!details || submitting}
              className="flex-1 py-3 rounded-xl bg-blue-600 text-white font-bold text-sm disabled:opacity-40 flex items-center justify-center gap-1">
              {submitting ? 'እየተላከ...' : '📨 ጥያቄውን ላክ'}
            </button>
          </div>
        </div>
      );
    }

    (function(){
      try {
        if (!window.React || !window.ReactDOM) {
          document.getElementById('root').innerHTML = '<div style="padding:20px;color:#b91c1c;font-family:system-ui">Failed to load React CDN</div>';
          return;
        }
        ReactDOM.createRoot(document.getElementById('root')).render(<BuyerForm />);
      } catch (e) {
        document.getElementById('root').innerHTML = '<div style="padding:20px;color:#b91c1c;font-family:system-ui">UI Error: '+e.message+'</div>';
      }
    })();
  </script>
</body>
</html>
"""



@web_app.route('/')
def home():
    return (
        "<html><body style='font-family:sans-serif;padding:24px'>"
        "<h2>Adika Marketplace</h2>"
        "<p>Server is running.</p>"
        f"<p>WEBAPP_URL: <code>{WEBAPP_URL}</code></p>"
        "<ul>"
        "<li><a href='/seller-form'>/seller-form</a></li>"
        "<li><a href='/buyer-form'>/buyer-form</a></li>"
        "<li><a href='/explorer'>/explorer</a></li>"
        "<li><a href='/api/health'>/api/health</a></li>"
        "</ul></body></html>"
    ), 200, {"Content-Type": "text/html; charset=utf-8"}

@web_app.route('/seller-form')
def webapp_seller_form():
   return Response(SELLER_FORM_HTML, mimetype='text/html; charset=utf-8')

@web_app.route('/buyer-form')
def webapp_buyer_form():
   return Response(BUYER_FORM_HTML, mimetype='text/html; charset=utf-8')
def _send_notification_safe(notification_text: str, req_id: int, buyer_id: int):
    """Fire broker notifications from Flask thread without blocking or breaking loops."""
    if not bot_app:
        logger.warning("bot_app is None – cannot send notification")
        return

    def run_in_thread():
        try:
            from handlers import notify_brokers

            async def _notify():
                await notify_brokers(bot_app.bot, notification_text, req_id, buyer_id)

            # Prefer loop captured in Application post_init
            loop = bot_loop
            if loop is None:
                loop = getattr(bot_app, "loop", None)
            if loop is not None and getattr(loop, "is_running", lambda: False)():
                fut = asyncio.run_coroutine_threadsafe(_notify(), loop)
                try:
                    fut.result(timeout=120)
                except Exception as e:
                    logger.error(f"notify future error: {e}")
                return

            # Fallback: dedicated loop in this worker thread
            new_loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(new_loop)
                new_loop.run_until_complete(_notify())
            finally:
                try:
                    new_loop.close()
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"_send_notification_safe error: {e}", exc_info=True)

    threading.Thread(target=run_in_thread, daemon=True, name="notify-brokers").start()



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
       uid = int(user_id) if str(user_id).isdigit() else 0
       extra = {
               'fuel_type': fuel_type, 'transmission': transmission, 'mileage': mileage,
               'condition': condition or house_condition, 'bedrooms': bedrooms,
               'bathrooms': bathrooms, 'parking': parking, 'house_type': house_type,
               'car_type': car_type, 'negotiable': negotiable, 'urgent_sale': urgent_sale,
               'telegram_user': telegram_user
       }
       # Limit photos payload (max 3 compressed)
       safe_photos = []
       if isinstance(photos, list):
           for ph in photos[:3]:
               s = str(ph)
               if len(s) > 350000:
                   s = s[:350000]
               safe_photos.append(s)
       req_id = add_listing(
           user_chat_id=uid,
           user_name="WebApp User",
           req_type="SELL",
           main_category=(category or car_type or house_type or "መኪና"),
           sub_category=car_type if category == 'መኪና' else house_type,
           action_type="መሸጥ",
           property_type="",
           description=full_desc,
           price=str(price),
           phone=str(phone or ""),
           extra_data=extra,
           photos=safe_photos
       )
       # Retry without photos if insert failed (photo size / type issues)
       if not req_id and safe_photos:
           logger.warning("Retry add_listing without photos")
           req_id = add_listing(
               user_chat_id=uid,
               user_name="WebApp User",
               req_type="SELL",
               main_category=(category or car_type or house_type or "መኪና"),
               sub_category=car_type if category == 'መኪና' else house_type,
               action_type="መሸጥ",
               property_type="",
               description=full_desc,
               price=str(price),
               phone=str(phone or ""),
               extra_data=extra,
               photos=[]
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
           import models as _models
           detail = getattr(_models, "LAST_DB_ERROR", "") or ""
           msg = "Database ውስጥ ማስቀመጥ አልተቻለም።"
           if detail:
               msg = f"{msg} ({detail[:180]})"
           logger.error("submit failed detail=%s backend=%s", detail, getattr(_models, "_DB_BACKEND", "?"))
           return jsonify({"status": "error", "message": msg, "detail": detail}), 500
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
           main_category=(category or car_type or house_type or "መኪና"),
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
           import models as _models
           detail = getattr(_models, "LAST_DB_ERROR", "") or ""
           msg = "Database ውስጥ ማስቀመጥ አልተቻለም።"
           if detail:
               msg = f"{msg} ({detail[:180]})"
           logger.error("submit failed detail=%s backend=%s", detail, getattr(_models, "_DB_BACKEND", "?"))
           return jsonify({"status": "error", "message": msg, "detail": detail}), 500
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
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no" />
  <title>Adika Marketplace</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font-family: system-ui, -apple-system, sans-serif; background: #E8F3FC; color: #0f172a; }
    .wrap { max-width: 480px; margin: 0 auto; padding: 10px 10px 40px; min-height: 100vh; }
    .hdr { position: sticky; top: 0; z-index: 20; background: #D4E6F5; border-bottom: 1px solid #bfdbfe; padding: 8px; border-radius: 0 0 12px 12px; }
    .tabs { display: flex; gap: 8px; margin-bottom: 8px; }
    .tab { flex: 1; border: none; padding: 10px; border-radius: 12px; font-weight: 700; font-size: 12px; background: rgba(255,255,255,0.45); color: #475569; }
    .tab.on { background: #fff; color: #1d4ed8; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
    .search { width: 100%; padding: 10px 12px 10px 32px; border-radius: 12px; border: 1px solid #e2e8f0; background: #fff; font-size: 13px; }
    .search-wrap { position: relative; margin-bottom: 8px; }
    .search-wrap span { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); opacity: .5; }
    .cats { display: flex; gap: 6px; overflow-x: auto; padding-bottom: 4px; }
    .cat { flex: 0 0 auto; border: 1px solid #dbeafe; background: #fff; border-radius: 999px; padding: 6px 12px; font-size: 11px; font-weight: 600; color: #334155; }
    .cat.on { background: linear-gradient(90deg,#2563eb,#4f46e5); color: #fff; border-color: transparent; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 12px; }
    .card { background: #fff; border-radius: 16px; padding: 8px; box-shadow: 0 12px 30px rgba(0,0,0,.14); display: flex; flex-direction: column; }
    .img { width: 100%; height: 110px; border-radius: 12px; object-fit: cover; background: #e2e8f0; }
    .ph { height: 110px; border-radius: 12px; background: #e2e8f0; display:flex;align-items:center;justify-content:center;font-size:32px; }
    .title { font-weight: 700; font-size: 13px; margin-top: 8px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .sub { font-size: 11px; color: #64748b; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .price { font-weight: 800; color: #2563eb; font-size: 13px; margin-top: 6px; }
    .actions { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-top: 8px; }
    .btn { border: none; border-radius: 12px; padding: 8px; font-size: 16px; text-decoration: none; text-align: center; }
    .btn.call { background: #eff6ff; color: #1d4ed8; }
    .btn.chat { background: #f8fafc; color: #334155; }
    .meta { display: flex; justify-content: space-between; gap: 4px; margin-top: 4px; }
    .badge { font-size: 9px; background: rgba(0,0,0,.5); color: #fff; padding: 2px 6px; border-radius: 999px; }
    .empty, .err, .load { text-align: center; padding: 40px 16px; color: #64748b; font-size: 14px; }
    .err { color: #b91c1c; background: #fef2f2; border-radius: 12px; margin-top: 12px; }
    .more { display:block; margin: 16px auto; border: 1px solid #bfdbfe; background: #fff; color: #2563eb; border-radius: 999px; padding: 8px 18px; font-weight: 600; font-size: 12px; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hdr">
      <div class="tabs">
        <button class="tab on" id="tabSell" type="button">🛒 የገበያ ቦታ</button>
        <button class="tab" id="tabBuy" type="button">📋 የፈላጊዎች</button>
      </div>
      <div class="search-wrap">
        <span>🔍</span>
        <input class="search" id="q" placeholder="ፈልግ..." />
      </div>
      <div class="cats" id="cats"></div>
    </div>
    <div id="status" class="load">እየጫነ ነው…</div>
    <div class="grid" id="grid"></div>
    <button class="more" id="more" type="button" style="display:none">ተጨማሪ ይመልከቱ</button>
  </div>
  <script>
  (function () {
    try {
      var tg = (window.Telegram && window.Telegram.WebApp) ? window.Telegram.WebApp : null;
      if (tg) {
        try { tg.ready(); } catch (e) {}
        try { tg.expand(); } catch (e) {}
        try { tg.setHeaderColor('#2563eb'); } catch (e) {}
        try { tg.setBackgroundColor('#E8F3FC'); } catch (e) {}
      }

      var state = {
        tab: (new URLSearchParams(location.search).get('tab') === 'requests') ? 'requests' : 'marketplace',
        category: '',
        q: '',
        page: 1,
        hasMore: false,
        loading: false
      };

      var cats = [
        { id: '', label: '✨ ሁሉም' },
        { id: 'መኪና', label: '🚗 መኪና' },
        { id: 'ቤት', label: '🏠 ቤት / ቦታ' },
        { id: 'ንግድ', label: '🏢 የሥራ ቦታ' }
      ];

      var catsEl = document.getElementById('cats');
      var grid = document.getElementById('grid');
      var statusEl = document.getElementById('status');
      var moreBtn = document.getElementById('more');
      var tabSell = document.getElementById('tabSell');
      var tabBuy = document.getElementById('tabBuy');
      var qInput = document.getElementById('q');

      function esc(s) {
        return String(s == null ? '' : s)
          .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
      }

      function relativeTime(iso) {
        if (!iso) return '';
        try {
          var d = new Date(iso);
          var secs = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
          if (secs < 60) return 'Just now';
          if (secs < 3600) return Math.floor(secs / 60) + 'm ago';
          if (secs < 86400) return Math.floor(secs / 3600) + ' hrs ago';
          if (secs < 172800) return 'Yesterday';
          return Math.floor(secs / 86400) + 'd ago';
        } catch (e) { return ''; }
      }

      function renderCats() {
        catsEl.innerHTML = cats.map(function (c) {
          return '<button type="button" class="cat' + (state.category === c.id ? ' on' : '') +
            '" data-id="' + esc(c.id) + '">' + esc(c.label) + '</button>';
        }).join('');
      }

      function cardHtml(item) {
        try {
          var extra = item.extra_data || {};
          if (typeof extra === 'string') {
            try { extra = JSON.parse(extra); } catch (e) { extra = {}; }
          }
          var photos = item.photos || [];
          var img = photos.length ? '<img class="img" src="' + esc(photos[0]) + '" alt="" loading="lazy" onerror="this.style.display=\'none\'">' :
            '<div class="ph">' + (item.main_category === 'መኪና' || item.category === 'መኪና' ? '🚗' : '🏠') + '</div>';
          var title = (item.main_category || item.category || '') + (item.sub_category ? ' • ' + item.sub_category : '');
          var desc = (item.description || '').replace(/[📝💰📞⚡📢🔄📦]/g,'').slice(0, 42);
          var isSell = String(item.req_type || '').toUpperCase() === 'SELL';
          var price = (isSell ? '💰 ዋጋ: ' : '💰 በጀት: ') + (item.price || '—');
          var views = item.view_count || item.views_count || 0;
          var phone = item.phone ? String(item.phone).replace(/\s+/g,'') : '';
          var user = extra.telegram_user ? String(extra.telegram_user).replace('@','') : '';
          var callHref = phone ? ('tel:' + phone) : '#';
          var chatHref = user ? ('https://t.me/' + user) : (item.user_chat_id ? ('tg://user?id=' + item.user_chat_id) : '#');
          return '<div class="card">' +
            '<div style="position:relative">' + img +
            '<div class="meta" style="position:absolute;left:6px;right:6px;bottom:6px">' +
            '<span class="badge">👁️ ' + esc(views) + '</span>' +
            '<span class="badge">' + esc(relativeTime(item.created_at)) + '</span></div></div>' +
            '<div class="title">' + esc(title) + '</div>' +
            '<div class="sub">' + esc(desc) + '</div>' +
            '<div class="price">' + esc(price) + '</div>' +
            '<div class="actions">' +
            '<a class="btn call" href="' + esc(callHref) + '">📞</a>' +
            '<a class="btn chat" href="' + esc(chatHref) + '" target="_blank" rel="noreferrer">💬</a>' +
            '</div></div>';
        } catch (e) {
          return '<div class="card"><div class="sub">Card error</div></div>';
        }
      }

      function setTabs() {
        tabSell.className = 'tab' + (state.tab === 'marketplace' ? ' on' : '');
        tabBuy.className = 'tab' + (state.tab === 'requests' ? ' on' : '');
      }

      async function load(append) {
        if (state.loading) return;
        state.loading = true;
        if (!append) {
          statusEl.style.display = 'block';
          statusEl.className = 'load';
          statusEl.textContent = 'እየጫነ ነው…';
          grid.innerHTML = '';
        }
        try {
          var page = append ? state.page + 1 : 1;
          var qs = new URLSearchParams({
            page: String(page),
            limit: '12',
            type: state.tab === 'marketplace' ? 'SELL' : 'BUY',
            order: 'DESC',
            active_only: '1'
          });
          if (state.category) qs.set('category', state.category);
          if (state.q) qs.set('q', state.q);
          var res = await fetch('/api/explorer/listings?' + qs.toString());
          var data = {};
          try { data = await res.json(); } catch (e) { data = {}; }
          if (!res.ok || data.status !== 'success') {
            statusEl.style.display = 'block';
            statusEl.className = 'err';
            statusEl.textContent = (data && data.message) ? data.message : ('API error ' + res.status);
            moreBtn.style.display = 'none';
            return;
          }
          var items = Array.isArray(data.items) ? data.items : [];
          if (!append) grid.innerHTML = '';
          if (!items.length && !append) {
            statusEl.style.display = 'block';
            statusEl.className = 'empty';
            statusEl.textContent = 'ምንም ንብረት አልተገኘም';
          } else {
            statusEl.style.display = 'none';
            grid.innerHTML += items.map(cardHtml).join('');
          }
          state.page = page;
          state.hasMore = !!data.has_more;
          moreBtn.style.display = state.hasMore ? 'block' : 'none';
        } catch (e) {
          statusEl.style.display = 'block';
          statusEl.className = 'err';
          statusEl.textContent = 'Network error: ' + (e && e.message ? e.message : e);
        } finally {
          state.loading = false;
        }
      }

      tabSell.onclick = function () { state.tab = 'marketplace'; setTabs(); load(false); };
      tabBuy.onclick = function () { state.tab = 'requests'; setTabs(); load(false); };
      catsEl.onclick = function (ev) {
        var t = ev.target.closest('[data-id]');
        if (!t) return;
        state.category = t.getAttribute('data-id') || '';
        renderCats();
        load(false);
      };
      moreBtn.onclick = function () { load(true); };
      var t = null;
      qInput.oninput = function () {
        clearTimeout(t);
        t = setTimeout(function () {
          state.q = qInput.value.trim();
          load(false);
        }, 300);
      };

      renderCats();
      setTabs();
      load(false);
    } catch (e) {
      document.body.innerHTML = '<div class="err" style="margin:20px">UI Error: ' +
        (e && e.message ? e.message : e) + '</div>';
    }
  })();
  </script>
</body>
</html>
"""

@web_app.route('/explorer')
def explorer_page():
    r = Response(EXPLORER_HTML, mimetype='text/html; charset=utf-8')
    r.headers['Cache-Control'] = 'no-store'
    return r




@web_app.route('/api/health', methods=['GET'])
def api_health():
    """Diagnostics — reports postgres vs temporary sqlite."""
    import config as app_config
    from models import get_db_connection, _DB_BACKEND
    backend = getattr(app_config, "DB_BACKEND", None) or _DB_BACKEND
    info = {
        "ok": True,
        "database": backend if backend != "unknown" else ("postgres" if DATABASE_URL else "sqlite"),
        "persistent": backend == "postgres",
        "isTemporaryDb": backend != "postgres",
        "webapp_url": WEBAPP_URL,
    }
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS cnt FROM listings")
        row = cur.fetchone()
        info["listings_count"] = row["cnt"] if isinstance(row, dict) else (row[0] if row else 0)
        cur.execute("SELECT COUNT(*) AS cnt FROM brokers")
        row = cur.fetchone()
        info["brokers_count"] = row["cnt"] if isinstance(row, dict) else (row[0] if row else 0)
        try:
            conn.close()
        except Exception:
            pass
        # refresh backend after connect
        backend = getattr(app_config, "DB_BACKEND", None) or _DB_BACKEND
        info["database"] = backend
        info["persistent"] = backend == "postgres"
        info["isTemporaryDb"] = backend != "postgres"
    except Exception as e:
        info["ok"] = False
        info["error"] = str(e)
    return jsonify(info)


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
            where.append(f"(main_category = {p} OR category = {p})")
            params.append(category)
            params.append(category)
        if search:
            from models import is_postgres
            like = "ILIKE" if is_postgres() else "LIKE"
            where.append(f"(description {like} {p} OR price {like} {p} OR phone {like} {p})")
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
        safe_items = [_json_safe(it) for it in items]
        try:
            import config as app_config
            from models import _DB_BACKEND
            backend = getattr(app_config, "DB_BACKEND", None) or _DB_BACKEND
        except Exception:
            backend = "postgres" if DATABASE_URL else "sqlite"
        return jsonify({
            "status": "success",
            "page": page,
            "limit": limit,
            "total": int(total or 0),
            "has_more": bool(offset + limit < (total or 0)),
            "items": safe_items,
            "db": backend,
            "isTemporaryDb": backend != "postgres",
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
        from models import is_postgres
        if not is_postgres():
            try:
                conn.commit()
            except Exception:
                pass
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
        from models import is_postgres
        if not is_postgres():
            try:
                conn.commit()
            except Exception:
                pass
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
        from models import is_postgres
        if not is_postgres():
            try:
                conn.commit()
            except Exception:
                pass
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        logger.error(f"delete item error: {e}")
        return jsonify({"status": "error"}), 500


# ---------- Auto-Expiry / Cleanup Job ----------




@web_app.route('/api/stats', methods=['GET'])
def api_stats():
    try:
        stats = get_platform_stats()
        return jsonify({"status": "success", **stats})
    except Exception as e:
        logger.error(f"api_stats: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@web_app.route('/api/brokers', methods=['GET'])
def api_brokers():
    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = min(15, max(1, int(request.args.get("limit", 12))))
        offset = (page - 1) * limit
        sub_city = request.args.get("sub_city") or None
        brokers = get_active_brokers(sub_city=sub_city, status="approved", limit=limit, offset=offset)
        total = count_brokers(status="approved")
        # Sanitize for JSON
        items = []
        for b in brokers:
            items.append({
                "id": b.get("id"),
                "chat_id": b.get("chat_id"),
                "full_name": b.get("full_name"),
                "phone": b.get("phone"),
                "username": b.get("username"),
                "sub_city": b.get("sub_city"),
                "specialty": b.get("specialty") or b.get("role_type"),
                "rating": float(b.get("rating") or 5),
                "total_ratings": b.get("total_ratings") or 0,
                "is_online": bool(b.get("is_online", True)),
                "status": b.get("status"),
            })
        return jsonify({
            "status": "success",
            "page": page,
            "limit": limit,
            "total": total,
            "has_more": offset + limit < total,
            "items": items,
        })
    except Exception as e:
        logger.error(f"api_brokers: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@web_app.route('/api/listings', methods=['GET'])
def api_listings_alias():
    """Alias with strict pagination (10-15 max)."""
    return api_explorer_listings()



def run_flask():
    """Start Flask HTTP server (Mini App + REST API) on 0.0.0.0:PORT."""
    port = int(PORT or 8080)
    logger.info("Starting Flask on 0.0.0.0:%s", port)
    web_app.run(host="0.0.0.0", port=port, use_reloader=False, threaded=True)
