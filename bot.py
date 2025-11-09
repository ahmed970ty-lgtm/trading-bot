from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import ta
import json
import logging
from pathlib import Path

# ==================== إعدادات التسجيل ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== الإعدادات ====================
TOKEN = "8366438891:AAGowx9iPvQdYGQ9sNArJ_50lrsaSckrRqk"
TWELVE_DATA_API_KEY = "de24b2541d564eb19684408b7367c6b7"
DEVELOPER_USER_ID = "5523707961"

# ==================== نظام إدارة المستخدمين ====================
class UserManager:
    def __init__(self, users_file="users.json"):
        self.users_file = users_file
        self.load_users()
    
    def load_users(self):
        """تحميل بيانات المستخدمين من ملف JSON"""
        try:
            if Path(self.users_file).exists():
                with open(self.users_file, 'r', encoding='utf-8') as f:
                    self.users = json.load(f)
            else:
                self.users = {}
                self.save_users()
        except Exception as e:
            logger.error(f"خطأ في تحميل المستخدمين: {e}")
            self.users = {}
    
    def save_users(self):
        """حفظ بيانات المستخدمين"""
        try:
            with open(self.users_file, 'w', encoding='utf-8') as f:
                json.dump(self.users, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"خطأ في حفظ المستخدمين: {e}")
    
    def add_user(self, user_id, user_name, duration_days=90):
        """إضافة مستخدم جديد"""
        expiry_date = (datetime.now() + timedelta(days=duration_days)).strftime("%Y-%m-%d")
        self.users[str(user_id)] = {
            "name": user_name,
            "expiry": expiry_date,
            "join_date": datetime.now().strftime("%Y-%m-%d"),
            "usage_count": 0
        }
        self.save_users()
        return True
    
    def is_authorized(self, user_id):
        """التحقق من صلاحية المستخدم"""
        user_data = self.users.get(str(user_id))
        if user_data:
            expiry_date = datetime.strptime(user_data["expiry"], "%Y-%m-%d")
            if datetime.now() < expiry_date:
                user_data["usage_count"] += 1
                self.save_users()
                return True, user_data
        return False, None

# ==================== نظام التحليل الفني ====================
class TechnicalAnalyzer:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.twelvedata.com"
    
    def get_historical_data(self, symbol, interval="15min", outputsize=100):
        """جلب البيانات التاريخية"""
        try:
            params = {
                'symbol': symbol,
                'interval': interval,
                'outputsize': outputsize,
                'apikey': self.api_key
            }
            
            response = requests.get(f"{self.base_url}/time_series", params=params, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                if 'values' in data and data['values']:
                    df = pd.DataFrame(data['values'])
                    df['datetime'] = pd.to_datetime(df['datetime'])
                    df['open'] = df['open'].astype(float)
                    df['high'] = df['high'].astype(float)
                    df['low'] = df['low'].astype(float)
                    df['close'] = df['close'].astype(float)
                    return df.sort_values('datetime')
                    
        except Exception as e:
            logger.error(f"خطأ في جلب البيانات: {e}")
        
        return None
    
    def calculate_indicators(self, df):
        """حساب المؤشرات الفنية"""
        if df is None or len(df) < 20:
            return None
            
        try:
            # RSI
            df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
            
            # MACD
            macd = ta.trend.MACD(df['close'])
            df['macd'] = macd.macd()
            df['macd_signal'] = macd.macd_signal()
            
            # المتوسطات المتحركة
            df['sma_20'] = ta.trend.SMAIndicator(df['close'], window=20).sma_indicator()
            df['sma_50'] = ta.trend.SMAIndicator(df['close'], window=50).sma_indicator()
            
            # Bollinger Bands
            bollinger = ta.volatility.BollingerBands(df['close'], window=20, window_dev=2)
            df['bb_upper'] = bollinger.bollinger_hband()
            df['bb_lower'] = bollinger.bollinger_lband()
            
            # الدعم والمقاومة
            df['support'] = df['low'].rolling(window=10).min()
            df['resistance'] = df['high'].rolling(window=10).max()
            
            return df
            
        except Exception as e:
            logger.error(f"خطأ في حساب المؤشرات: {e}")
            return None
    
    def generate_signals(self, df):
        """توليد إشارات التداول"""
        if df is None or len(df) < 50:
            return None
            
        current = df.iloc[-1]
        signals = []
        confidence = 0
        
        # إشارات RSI
        if current['rsi'] < 30:
            signals.append("🟢 RSI في منطقة ذروة البيع")
            confidence += 25
        elif current['rsi'] > 70:
            signals.append("🔴 RSI في منطقة ذروة الشراء")
            confidence += 25
        
        # إشارات MACD
        if current['macd'] > current['macd_signal']:
            signals.append("🟢 MACD إيجابي")
            confidence += 20
        else:
            signals.append("🔴 MACD سلبي")
            confidence += 20
        
        # إشارات المتوسطات
        if current['sma_20'] > current['sma_50']:
            signals.append("🟢 اتجاه صاعد")
            confidence += 15
        else:
            signals.append("🔴 اتجاه هابط")
            confidence += 15
        
        return {
            'signals': signals,
            'confidence': min(confidence, 100),
            'total_signals': len(signals)
        }
    
    def calculate_entry_exit_points(self, df, current_price):
        """حساب نقاط الدخول والخروج"""
        if df is None:
            return None
            
        current = df.iloc[-1]
        
        # نقاط الدخول
        buy_entry = round(current['bb_lower'] * 0.998, 4)
        sell_entry = round(current['bb_upper'] * 1.002, 4)
        
        # وقف الخسارة
        buy_stop_loss = round(current['support'] * 0.995, 4)
        sell_stop_loss = round(current['resistance'] * 1.005, 4)
        
        # أهداف الربح
        buy_take_profit = [
            round(current_price * 1.005, 4),
            round(current_price * 1.01, 4),
            round(current['resistance'] * 0.998, 4)
        ]
        
        sell_take_profit = [
            round(current_price * 0.995, 4),
            round(current_price * 0.99, 4),
            round(current['support'] * 1.002, 4)
        ]
        
        return {
            'buy': {
                'entry': buy_entry,
                'stop_loss': buy_stop_loss,
                'take_profit': buy_take_profit
            },
            'sell': {
                'entry': sell_entry,
                'stop_loss': sell_stop_loss,
                'take_profit': sell_take_profit
            }
        }

# ==================== تهيئة الأنظمة ====================
user_manager = UserManager()
technical_analyzer = TechnicalAnalyzer(TWELVE_DATA_API_KEY)

ASSETS = {
    "الذهب": {"symbol": "XAU/USD", "emoji": "🪙"},
    "الفضة": {"symbol": "XAG/USD", "emoji": "⚪"}, 
    "النفط": {"symbol": "USOIL", "emoji": "🛢️"},
    "يورو/دولار": {"symbol": "EUR/USD", "emoji": "💶"},
    "جنيه/دولار": {"symbol": "GBP/USD", "emoji": "💷"},
    "دولار/ين": {"symbol": "USD/JPY", "emoji": "💴"},
    "بتكوين": {"symbol": "BTC/USD", "emoji": "₿"},
    "إيثريوم": {"symbol": "ETH/USD", "emoji": "🔷"}
}

# ==================== نظام لوحات المفاتيح ====================
def get_main_keyboard(user_id):
    """لوحة المفاتيح الرئيسية"""
    is_authorized, user_data = user_manager.is_authorized(user_id)
    
    keyboard = []
    
    if is_authorized:
        # للمستخدمين المدفوعين
        keyboard.append([
            InlineKeyboardButton("🪙 الذهب", callback_data="asset_الذهب"),
            InlineKeyboardButton("⚪ الفضة", callback_data="asset_الفضة")
        ])
        keyboard.append([
            InlineKeyboardButton("🛢️ النفط", callback_data="asset_النفط"),
            InlineKeyboardButton("💶 يورو/دولار", callback_data="asset_يورو/دولار")
        ])
        keyboard.append([
            InlineKeyboardButton("💷 جنيه/دولار", callback_data="asset_جنيه/دولار"),
            InlineKeyboardButton("💴 دولار/ين", callback_data="asset_دولار/ين")
        ])
        keyboard.append([
            InlineKeyboardButton("₿ بتكوين", callback_data="asset_بتكوين"),
            InlineKeyboardButton("🔷 إيثريوم", callback_data="asset_إيثريوم")
        ])
        keyboard.append([
            InlineKeyboardButton("📊 جميع الأسعار", callback_data="all_prices")
        ])
    else:
        # للمستخدمين المجانيين
        keyboard.append([
            InlineKeyboardButton("🔍 معرفة الـ ID الخاص بي", callback_data="show_my_id")
        ])
        keyboard.append([
            InlineKeyboardButton("💳 شراء البوت", callback_data="buy_bot"),
            InlineKeyboardButton("📞 دعم فوري", url="https://t.me/TradingSupportBot")
        ])
    
    keyboard.append([
        InlineKeyboardButton("🆘 المساعدة", callback_data="help")
    ])
    
    return InlineKeyboardMarkup(keyboard)

def get_payment_keyboard():
    """لوحة مفاتيح الدفع"""
    keyboard = [
        [
            InlineKeyboardButton("💳 MasterCard", callback_data="payment_mastercard"),
            InlineKeyboardButton("₿ OKX P2P", callback_data="payment_okx")
        ],
        [
            InlineKeyboardButton("📞 دعم فوري", url="https://t.me/TradingSupportBot"),
            InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# ==================== الأوامر الرئيسية ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدء البوت"""
    try:
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name
        
        is_authorized, user_data = user_manager.is_authorized(user_id)
        
        if is_authorized:
            welcome_text = f"""
🎯 مرحباً بك {user_data['name']}!

✅ حسابك مفعل حتى: {user_data["expiry"]}
📊 عدد التحليلات: {user_data['usage_count']}

📈 اختر الأصل للتحليل:
"""
        else:
            welcome_text = f"""
🔒 بوت التحليل الفني المميز

👋 مرحباً {user_name}!

🆔 User ID الخاص بك: {user_id}

❌ لست مشتركاً في البوت المميز

💎 المميزات:
• تحليل فني احترافي
• توصيات ذكية
• إدارة مخاطر
• أسعار حية

💰 سعر الاشتراك: 30 دولار
⏰ مدة الاشتراك: 2 أشهر
📞 الدعم: @ah_dxo
"""
        
        await update.message.reply_text(
            welcome_text,
            reply_markup=get_main_keyboard(user_id)
        )
    except Exception as e:
        logger.error(f"خطأ في أمر start: {e}")

async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة النقر على الأزرار"""
    try:
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        data = query.data
        
        is_authorized, user_data = user_manager.is_authorized(user_id)
        
        if data == "show_my_id":
            user_info = f"""
👤 معلومات المستخدم:

🆔 User ID: {user_id}
📛 الاسم: {query.from_user.first_name}
🔗 Username: @{query.from_user.username or 'لا يوجد'}

💡 احفظ هذا الرقم وأرسله للدعم للتفعيل
"""
            await query.message.reply_text(user_info)
            return
        
        elif data == "buy_bot":
            await show_payment_options(query, user_id)
            return
        
        elif data.startswith("payment_"):
            await handle_payment_method(query, data, user_id)
            return
        
        elif data == "back_to_main":
            await start_callback(query, user_id)
            return
        
        elif data == "help":
            await send_help(query, user_id)
            return
        
        # التحقق من الصلاحية للأوامر الأخرى
        if not is_authorized and (data.startswith("asset_") or data == "all_prices"):
            await query.message.reply_text(
                "❌ غير مصرح لك باستخدام البوت\n\nيجب شراء البوت أولاً للوصول إلى هذه الميزات.\n\n💵 السعر: 30 دولار لمدة 3 أشهر\n📞 للشراء اضغط على زر شراء البوت"
            )
            return
        
        if data.startswith("asset_"):
            asset_name = data.replace("asset_", "")
            await send_analysis(query, asset_name, user_id)
        
        elif data == "all_prices":
            await send_all_prices(query, user_id)
            
    except Exception as e:
        logger.error(f"خطأ في handle_button_click: {e}")
        try:
            await query.message.reply_text("❌ حدث خطأ في المعالجة، يرجى المحاولة مرة أخرى")
        except:
            pass

async def show_payment_options(query, user_id):
    """عرض خيارات الدفع"""
    try:
        payment_message = f"""
💰 مربع الدفع الذهبي 💰

🎯 باقة الاشتراك المميز
💵 السعر: 30 دولار
⏰ المدة: 2 أشهر
✨ المميزات: تحليل فني متقدم + توصيات ذكية

💳 طرق الدفع المتاحة:

1️⃣ 💳 MasterCard / فيزا كارد
   - الدفع المباشر بالبطاقة
   - فوري وآمن

2️⃣ ₿ منصة OKX عن طريق P2P
   - شراء بالعملات الرقمية
   - سهل وسريع

📞 للإستفسار أو المساعدة في الدفع:
@ah_dxo

🆔 لا تنسى إرسال User ID الخاص بك: {user_id}
"""

        await query.message.edit_text(
            text=payment_message,
            reply_markup=get_payment_keyboard()
        )
    except Exception as e:
        logger.error(f"خطأ في show_payment_options: {e}")

async def handle_payment_method(query, payment_method, user_id):
    """معالجة طريقة الدفع المختارة"""
    try:
        if payment_method == "payment_mastercard":
            payment_info = f"""
💳 طريقة الدفع بـ MasterCard:

1. تواصل مع الدعم: @ah_dxo
2. أرسل User ID الخاص بك: {user_id}
3. سيتم إرسال رابط الدفع الآمن
4. أكمل عملية الدفع
5. سيتم تفعيل حسابك فوراً

⚡ مميزات الدفع بالبطاقة:
   • سريع وآمن
   • مدفوعات عالمية
   • تأكيد فوري
"""

        elif payment_method == "payment_okx":
            payment_info = f"""
₿ طريقة الدفع بـ OKX P2P:

1. افتح تطبيق OKX
2. اذهب إلى قسم P2P
3. اشترِ USDT بقيمة 30 دولار
4. تواصل مع الدعم: @ah_dxo
5. أرسل إشعار الدفع + User ID

🔄 خطوات التحويل:
   - اشترِ USDT من OKX P2P
   - احفظ proof of payment
   - أرسل للدعم للتأكيد
"""

        final_message = f"""
💳 معلومات الدفع 💳

{payment_info}

📞 للإستفسار أو المساعدة: @TradingSupportBot
🆔 User ID الخاص بك: {user_id}
"""

        await query.message.edit_text(
            text=final_message,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📞 التواصل مع الدعم", url="https://t.me/TradingSupportBot"),
                InlineKeyboardButton("🔙 رجوع للخيارات", callback_data="buy_bot")
            ]])
        )
    except Exception as e:
        logger.error(f"خطأ في handle_payment_method: {e}")

async def start_callback(query, user_id):
    """بدء البوت من callback"""
    try:
        user_name = query.from_user.first_name
        is_authorized, user_data = user_manager.is_authorized(user_id)
        
        if is_authorized:
            welcome_text = f"""
🎯 مرحباً بك {user_data['name']}!

✅ حسابك مفعل حتى: {user_data["expiry"]}
📊 عدد التحليلات: {user_data['usage_count']}

📈 اختر الأصل للتحليل:
"""
        else:
            welcome_text = f"""
🔒 بوت التحليل الفني المميز

👋 مرحباً {user_name}!

🆔 User ID الخاص بك: {user_id}

💰 اشترك الآن بسعر 30 دولار لمدة 2 أشهر
"""

        await query.edit_message_text(
            text=welcome_text,
            reply_markup=get_main_keyboard(user_id)
        )
    except Exception as e:
        logger.error(f"خطأ في start_callback: {e}")

async def send_analysis(query, asset_name, user_id):
    """إرسال تحليل للأصل المختار"""
    try:
        is_authorized, user_data = user_manager.is_authorized(user_id)
        if not is_authorized:
            await query.message.reply_text("❌ صلاحية استخدامك انتهت.")
            return
        
        asset_info = ASSETS.get(asset_name)
        if not asset_info:
            await query.message.reply_text("❌ هذا الأصل غير متوفر")
            return
        
        symbol = asset_info["symbol"]
        emoji = asset_info["emoji"]
        
        processing_msg = await query.message.reply_text(f"⏳ جاري تحليل {emoji} {asset_name}...")
        
        try:
            df = technical_analyzer.get_historical_data(symbol, "15min", 100)
            
            if df is None or len(df) < 50:
                await processing_msg.edit_text(f"❌ لا توجد بيانات لـ {asset_name}")
                return
            
            df = technical_analyzer.calculate_indicators(df)
            
            if df is None:
                await processing_msg.edit_text(f"❌ خطأ في تحليل {asset_name}")
                return
            
            current_data = df.iloc[-1]
            current_price = current_data['close']
            
            trading_signals = technical_analyzer.generate_signals(df)
            entry_exit_points = technical_analyzer.calculate_entry_exit_points(df, current_price)
            
            # بناء التقرير
            message = f"🎯 تحليل {asset_name}\n"
            message += f"{emoji} {asset_name} | 👤 {user_data['name']}\n\n"
            
            message += f"💰 السعر: {current_price:.{4 if '/' in symbol else 2}f}\n"
            message += f"📈 RSI: {current_data['rsi']:.1f} {'🔴' if current_data['rsi'] > 70 else '🟢' if current_data['rsi'] < 30 else '⚪'}\n"
            message += f"📊 MACD: {current_data['macd']:.4f}\n\n"
            
            if trading_signals and trading_signals['signals']:
                message += f"📢 إشارات ({trading_signals['confidence']}%):\n"
                for signal in trading_signals['signals']:
                    message += f"• {signal}\n"
                message += "\n"
            
            if entry_exit_points:
                if trading_signals['confidence'] >= 60:
                    points = entry_exit_points['buy']
                    action = "🟢 شراء"
                else:
                    points = entry_exit_points['sell']
                    action = "🔴 بيع"
                
                message += f"🎯 التوصية: {action}\n"
                message += f"📍 الدخول: {points['entry']}\n"
                message += f"🛡️ وقف: {points['stop_loss']}\n"
                message += f"🎯 أهداف:\n"
                for i, target in enumerate(points['take_profit'], 1):
                    message += f"   {i}. {target}\n"
            
            message += f"\n⏰ {datetime.now().strftime('%H:%M:%S')}\n"
            message += "⚠️ تحليل للمساعدة فقط"
            
            await processing_msg.delete()
            await query.message.reply_text(
                message,
                reply_markup=get_main_keyboard(user_id)
            )
            
        except Exception as e:
            await processing_msg.edit_text(f"❌ خطأ في التحليل: {str(e)}")
            
    except Exception as e:
        logger.error(f"خطأ في send_analysis: {e}")

async def send_all_prices(query, user_id):
    """إرسال جميع الأسعار"""
    try:
        is_authorized, user_data = user_manager.is_authorized(user_id)
        if not is_authorized:
            return
        
        processing_msg = await query.message.reply_text("📡 جاري جلب الأسعار...")
        
        message = "💹 الأسعار الحية\n\n"
        
        for asset_name, asset_info in ASSETS.items():
            symbol = asset_info["symbol"]
            emoji = asset_info["emoji"]
            
            try:
                df = technical_analyzer.get_historical_data(symbol, "1min", 2)
                if df is not None and len(df) > 0:
                    current_price = df.iloc[-1]['close']
                    message += f"{emoji} {asset_name}: {current_price:.{4 if '/' in symbol else 2}f}\n"
                else:
                    message += f"{emoji} {asset_name}: ❌ غير متوفر\n"
            except:
                message += f"{emoji} {asset_name}: ❌ خطأ\n"
        
        message += f"\n🕒 {datetime.now().strftime('%H:%M:%S')}"
        
        await processing_msg.delete()
        await query.message.reply_text(
            message,
            reply_markup=get_main_keyboard(user_id)
        )
    except Exception as e:
        logger.error(f"خطأ في send_all_prices: {e}")

async def send_help(query, user_id):
    """إرسال رسالة المساعدة"""
    try:
        help_text = """
🆘 دليل الاستخدام

🎯 للمشتركين:
• اختر الأصل للتحليل
• احصل على توصيات فورية
• استخدم نقاط الدخول والخروج

💰 طرق الدفع:
• 💳 MasterCard / فيزا
• ₿ OKX P2P

💵 السعر: 30 دولار لمدة 2 أشهر

📞 الدعم الفوري: @ah_dxo

⚠️ تحذير: 
هذا البوت لأغراض تعليمية ومساعدة في التحليل
ولا يعد بتعويض عن أي خسائر
"""
        await query.message.reply_text(
            help_text,
            reply_markup=get_main_keyboard(user_id)
        )
    except Exception as e:
        logger.error(f"خطأ في send_help: {e}")

# ==================== أوامر الإدارة ====================
async def add_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر إضافة مستخدم (للمطور فقط)"""
    try:
        user_id = update.effective_user.id
        
        if user_id != DEVELOPER_USER_ID:
            await update.message.reply_text("❌ ليس لديك صلاحية لهذا الأمر")
            return
        
        if len(context.args) < 2:
            await update.message.reply_text("❌ استخدام: /adduser <user_id> <user_name>")
            return
        
        try:
            target_user_id = int(context.args[0])
            user_name = ' '.join(context.args[1:])
            
            user_manager.add_user(target_user_id, user_name)
            await update.message.reply_text(f"✅ تم إضافة المستخدم {user_name} بنجاح!")
            
        except ValueError:
            await update.message.reply_text("❌ user_id يجب أن يكون رقماً")
    except Exception as e:
        logger.error(f"خطأ في add_user_command: {e}")

# ==================== معالجة الأخطاء العامة ====================
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الأخطاء العامة"""
    try:
        logger.error(f"حدث خطأ: {context.error}")
    except Exception as e:
        logger.error(f"خطأ في معالجة الخطأ: {e}")

# ==================== التشغيل الرئيسي ====================
def main():
    if not TOKEN or TOKEN == "8366438891:AAG...":
        print("❌ لم يتم تعيين توكن البوت!")
        return
    
    try:
        app = Application.builder().token(TOKEN).build()
        
        # إضافة المعالجات
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("adduser", add_user_command))
        app.add_handler(CallbackQueryHandler(handle_button_click))
        
        # إضافة معالج الأخطاء
        app.add_error_handler(error_handler)
        
        # إضافة المستخدم تلقائياً عند التشغيل
        user_manager.add_user(DEVELOPER_USER_ID, "Developer", 365)
        print("✅ تم إضافة Developer تلقائياً")
        
        print("🤖 البوت المحمي شغال!")
        print("🔒 يعمل بنظام User ID")
        print("💵 للمستخدمين المدفوعين فقط - السعر: 30 دولار")
        print("📞 دعم الدفع: @TradingSupportBot")
        print("👤 Developer User ID: 5523707961")
        print("⚡ Polling interval: 2.0 ثانية")
        
        # التشغيل مع poll_interval=2.0
        app.run_polling(poll_interval=2.0, drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"خطأ في التشغيل الرئيسي: {e}")
        print(f"❌ فشل تشغيل البوت: {e}")

if __name__ == '__main__':
    main()