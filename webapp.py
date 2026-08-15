# ==============================================================================
# webapp.py — Flask Mini App + REST API
# ==============================================================================
import json
import asyncio
import random
import threading
from flask import Flask, request, jsonify, Response

from config import (
    logger, PORT, MAX_IMAGE_BYTES, ADMIN_CHAT_ID_INT, DATABASE_URL, WEBAPP_URL,
)
from models import (
    get_db_connection, get_placeholder, add_listing, get_listing_by_id,
    update_listing_status, save_search_alert, expire_old_listings,
)

# bot_app set from main for notifications
bot_app = None
bot_loop = None  # set from main post_init

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


def run_flask():
   port = int(os.environ.get("PORT", 8080))
   web_app.run(host="0.0.0.0", port=port, use_reloader=False)



# ==============================================================================
# 3. DATABASE CONNECTION & INITIALIZATION
# ==============================================================================

