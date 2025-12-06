import discord
from discord.ext import commands
from discord import app_commands
from discord.utils import get
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import asyncio
import time
import os
import random
import string
from collections import defaultdict
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

# ----- CONFIGURACIÓN -----
bot = commands.Bot(command_prefix="?", intents=discord.Intents.all(), help_command=None)
analyzer = SentimentIntensityAnalyzer()
startup_time = discord.utils.utcnow()  # Tracking del inicio del bot

# Obtener OWNER_ID desde variable de entorno
OWNER_ID = int(os.getenv('OWNER_ID', '0')) if os.getenv('OWNER_ID') else None
if OWNER_ID:
    bot.owner_id = OWNER_ID

# Conexión a la BD
def get_db_connection():
    return psycopg2.connect(os.getenv('DATABASE_URL'))

PALABRAS_PROHIBIDAS = [
    "idiota", "tonto", "estúpido", "imbécil", "pendejo", "puta",
    "payaso", "perra", "mierda", "asco", "callate", "cállate",
    "hijo de puta", "desgraciado", "basura", "retrasado", "subnormal",
    "degenerado", "muérete", "muere", "mal nacido", "cojones", "coño",
    "gilipolla", "gilipollas", "cabrón", "cabron", "zopenco", "majadero",
    "patán", "patan", "canalla", "bellaco", "granuja", "pícaro", "picaro",
    "sinvergüenza", "desvergonzado", "descarado", "villano", "malvado",
    "infame", "deshonroso", "depravado", "libertino", "cochino", "puerco",
    "asqueroso", "repugnante", "nauseabundo", "putero", "pendejada",
    "maricón", "maricon", "marica", "mariquita", "negrería", "negrera",
    "desgraciada", "prostituta", "ramera", "fulana", "tal", "tarado",
    "tarada", "discapacitado", "discapacitada", "down", "retarded",
    "downie", "enfermo", "enferma", "psicópata", "psicopata", "sociopata",
    "sociópata", "delincuente", "criminal", "asesino", "violador", "violadora",
    "pedófilo", "pedofilo", "satánico", "satánico", "demoníaco", "demoniaco",
    "hijo de satán", "hijo de satan", "maldita", "maldito", "condenada",
    "condenado", "infierno", "demonio", "diablo", "Satán", "Satan",
    "vete al infierno", "vete a la mierda", "vete a freír espárragos",
    "que te jodan", "chupamiedas", "come mierda", "tragamierda",
    "tragasables", "lambeculos", "lameculos", "lambehuevas", "lamehuevas",
    "maestra puta", "maestro puto", "profesor puto", "profesora puta",
    "basurilla", "basurilla", "escoria", "gusano", "lombriz",
    "sabandija", "sabandija", "alimaña", "alimana", "bestia",
    "animal", "perro", "perra", "burro", "burra", "asno", "asna",
    "cerdo", "cerda", "chancho", "chancha", "marrano", "marrana",
    "rata", "ratón", "serpiente", "culebra", "víbora", "vibora",
    "escorpión", "escorpion", "sapo", "sapia", "boca", "boquita",
    "fea", "feo", "horrible", "horrorosa", "horroroso", "repulsiva",
    "repulsivo", "desagradable", "ofensiva", "ofensivo", "insultante",
    "denigrante", "humillante", "vergonzosa", "vergonzoso", "bochornosa",
    "bochornoso", "deshonrosa", "deshonroso", "infamia", "villanía", "villanía",
]

SILENCE_ROLE_NAME = "Silenciado"
LOGS_CHANNEL_NAME = "logs-mod"
logs_channel_id = {}  # guild_id → channel_id (para guardar el canal de logs personalizado)

# ----- TRACKERS -----
advertencias = defaultdict(int)         # usuario.id → número de advertencias
toxicidad_puntos = defaultdict(int)     # usuario.id → puntos de toxicidad
ultimo_insulto = defaultdict(str)       # usuario.id → a quién insultó último
mensajes_rapidos = defaultdict(list)    # usuario.id → timestamps de mensajes
ultimo_mensaje = defaultdict(str)       # usuario.id → último mensaje
contador_repetidos = defaultdict(int)   # usuario.id → cuántas veces repitió mensaje seguido
mensajes_enviados = defaultdict(int)    # usuario.id → total de mensajes enviados
mute_historial = defaultdict(list)      # usuario.id → lista de (fecha, duración en segundos)
shadowmuted = set()                     # set de usuario.id → usuarios en shadowmute
codigos_verificacion = {}               # usuario.id → código de verificación
reportes = []                            # lista de (usuario reportador, usuario reportado, motivo, fecha)
ultimo_mute_enviado = {}                 # usuario.id → timestamp del último DM de mute enviado
eventos_tiempo_real = []                 # lista de eventos en tiempo real (últimos 50)
MAX_EVENTOS_ALMACENADOS = 50             # máximo de eventos a almacenar
mensajes_cache = defaultdict(dict)       # guild.id → {message.id: (author, content, timestamp)}
ultimos_audits_vistos = defaultdict(int) # guild.id → último audit log visto

async def agregar_evento_real(tipo, descripcion, detalles="", guild=None):
    """Agrega un evento a la lista de tiempo real y lo envía al canal de logs"""
    timestamp = discord.utils.utcnow().strftime("%d/%m/%y %H:%M:%S")
    evento = {
        "tipo": tipo,
        "descripcion": descripcion,
        "detalles": detalles,
        "timestamp": timestamp
    }
    eventos_tiempo_real.append(evento)
    # Mantener solo los últimos 50 eventos
    if len(eventos_tiempo_real) > MAX_EVENTOS_ALMACENADOS:
        eventos_tiempo_real.pop(0)
    
    # Enviar al canal de logs en Discord si está disponible
    if guild:
        try:
            # Intentar obtener el canal personalizado primero
            canal_logs = None
            if guild.id in logs_channel_id:
                canal_logs = guild.get_channel(logs_channel_id[guild.id])
            
            # Si no hay personalizado, buscar el canal por defecto
            if not canal_logs:
                canal_logs = get(guild.text_channels, name=LOGS_CHANNEL_NAME)
            
            if canal_logs:
                embed = discord.Embed(
                    title=f"{tipo} Evento en Tiempo Real",
                    description=f"**{descripcion}**\n{detalles}",
                    color=discord.Color.blue(),
                    timestamp=discord.utils.utcnow()
                )
                embed.set_footer(text=f"⏱️ Evento automático")
                await canal_logs.send(embed=embed)
                print(f"✅ Evento enviado a {canal_logs.name}: {tipo} {descripcion}")
            else:
                print(f"⚠️ Canal de logs no configurado en {guild.name}. Usa ?setlogschannel")
        except Exception as e:
            print(f"❌ Error enviando evento a logs: {e}")

# Parámetros de moderación
ADVERTENCIAS_MAX = 2      # advertencias antes de mutear
VENTANA_TIEMPO = 5        # segundos
SPAM_MENSAJES = 5         # mensajes en ventana → spam
REPETICIONES_MAX = 3      # mensajes iguales seguidos → spam
MENTIONES_MAX = 4         # menciones por mensaje → spam

# ----- FUNCIONES UTILES -----
async def asegurar_rol_silencio(guild):
    rol = get(guild.roles, name=SILENCE_ROLE_NAME)
    if rol is None:
        rol = await guild.create_role(name=SILENCE_ROLE_NAME)
        for canal in guild.channels:
            await canal.set_permissions(rol, send_messages=False)
    return rol

class MuteConfirmView(discord.ui.View):
    def __init__(self, usuario, guild, segundos, razon, mensaje_id):
        super().__init__(timeout=300)
        self.usuario = usuario
        self.guild = guild
        self.segundos = segundos
        self.razon = razon
        self.mensaje_id = mensaje_id
        self.confirmado = False
    
    @discord.ui.button(label="✅ Confirmar Mute", style=discord.ButtonStyle.green)
    async def confirmar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != bot.owner_id:
            await interaction.response.defer()
            return
        self.confirmado = True
        await interaction.response.defer()
        await self.aplicar_mute()
    
    @discord.ui.button(label="❌ Cancelar", style=discord.ButtonStyle.red)
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != bot.owner_id:
            await interaction.response.defer()
            return
        await interaction.response.defer()
        await interaction.message.delete()
    
    async def aplicar_mute(self):
        try:
            rol = await asegurar_rol_silencio(self.guild)
            await self.usuario.add_roles(rol)
            
            fecha = discord.utils.utcnow().strftime("%d/%m/%Y %H:%M:%S")
            mute_historial[self.usuario.id].append((fecha, self.segundos, self.razon, self.mensaje_id))
            
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO muteos_log (usuario_id, usuario_nombre, duracion_segundos, guild_id) VALUES (%s, %s, %s, %s)",
                    (self.usuario.id, self.usuario.name, self.segundos, self.guild.id)
                )
                conn.commit()
                cur.close()
                conn.close()
            except Exception as e:
                print(f"Error guardando muteo en BD: {e}")
            
            await enviar_log(self.guild, f"🔇 MUTE CONFIRMADO | Usuario: {self.usuario.mention} ({self.usuario.id}) | Razón: {self.razon}")
            
            await asyncio.sleep(self.segundos)
            await self.usuario.remove_roles(rol)
        except Exception as e:
            print(f"Error aplicando mute: {e}")

async def silenciar_usuario(usuario, guild, segundos, razon="Sin especificar", mensaje_id=None):
    ahora = time.time()
    
    # Evitar duplicados: si se envió un DM hace menos de 1 segundo, ignorar
    if usuario.id in ultimo_mute_enviado:
        tiempo_desde_ultimo = ahora - ultimo_mute_enviado[usuario.id]
        if tiempo_desde_ultimo < 1.0:  # Menos de 1 segundo
            print(f"⏭️ Intento de mute duplicado para {usuario.id} ignorado (hace {tiempo_desde_ultimo:.2f}s)")
            return
    
    # Actualizar timestamp del último mute enviado
    ultimo_mute_enviado[usuario.id] = ahora
    
    try:
        owner = await bot.fetch_user(bot.owner_id)
        
        embed = discord.Embed(
            title="🔇 Confirmación de Mute",
            description=f"Un usuario ha alcanzado el límite de advertencias",
            color=discord.Color.red()
        )
        embed.add_field(name="👤 Usuario", value=f"{usuario.mention} ({usuario.id})", inline=False)
        embed.add_field(name="⚠️ Razón", value=razon, inline=False)
        embed.add_field(name="⏱️ Duración", value=f"{segundos} segundos", inline=False)
        
        view = MuteConfirmView(usuario, guild, segundos, razon, mensaje_id)
        await owner.send(embed=embed, view=view)
    except Exception as e:
        print(f"Error enviando DM de confirmación: {e}")

async def enviar_log(guild, mensaje):
    canal = get(guild.text_channels, name=LOGS_CHANNEL_NAME)
    if canal:
        await canal.send(mensaje)

def es_moderador_inmune(autor):
    """Verifica si el usuario es moderador, owner o admin (exento de detección de toxicidad)"""
    if not hasattr(autor, 'guild_permissions'):
        return False
    
    if autor.guild_permissions.administrator:
        return True
    
    roles_inmunidad = ["moderador", "mod", "owner", "admin", "administrador"]
    for rol in autor.roles:
        if rol.name.lower() in roles_inmunidad:
            return True
    
    return False

async def advertir_usuario(usuario, guild, razon, canal):
    advertencias[usuario.id] += 1
    warns = advertencias[usuario.id]
    
    # Intentar enviar DM al usuario (solo si aún no superó el límite)
    if warns <= ADVERTENCIAS_MAX:
        try:
            mensaje = f"⚠️ **Advertencia en {guild.name}**\n"
            mensaje += f"**Advertencias totales:** {warns}/{ADVERTENCIAS_MAX}\n"
            if warns == ADVERTENCIAS_MAX:
                mensaje += "🔴 **Próxima infracción resultará en muteo.**"
            await usuario.send(mensaje)
        except:
            pass  # Si el usuario tiene los DM cerrados, no pasa nada
    
    # Guardar en BD
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO advertencias_log (usuario_id, usuario_nombre, razon, numero_advertencia, guild_id) VALUES (%s, %s, %s, %s, %s)",
            (usuario.id, usuario.name, razon, warns, guild.id)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error guardando advertencia en BD: {e}")
    
    # Registrar en logs
    await enviar_log(guild, f"⚠️ ADVERTENCIA #{warns} | Usuario: {usuario.mention} ({usuario.id}) | Razón: {razon} | Canal: {canal.mention}")
    
    return warns

# ----- DETECCIÓN DE SPAM -----
def detectar_spam(message):
    # ✅ SPAM DESACTIVADO (solo toxicidad activa)
    return False, None

# ----- DETECCIÓN DE INSULTOS / PELEAS -----
def detectar_pelea(contenido, autor_id, referencia_id):
    insulto = any(p in contenido for p in PALABRAS_PROHIBIDAS)
    toxicidad = analyzer.polarity_scores(contenido)["neg"] > 0.6
    pelea_directa = False
    if referencia_id:
        if autor_id in ultimo_insulto and ultimo_insulto[autor_id] == referencia_id:
            pelea_directa = True
    return insulto or toxicidad or pelea_directa, insulto

# ----- EVENTOS -----
@bot.event
async def on_member_join(member):
    """Cuando alguien se une al servidor"""
    await agregar_evento_real("👋", "MEMBER_JOIN", f"{member.name} ({member.id})", member.guild)
    
    embed = discord.Embed(
        title=f"👋 ¡Bienvenido {member.name}!",
        description=f"Para acceder al servidor, debes verificarte.\n\n**EN EL SERVIDOR** (no aquí), usa:\n`?verify`\n\nEso te enviará un código por DM que deberás confirmar con:\n`?confirmar CÓDIGO`",
        color=discord.Color.green()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    
    try:
        await member.send(embed=embed)
        await enviar_log(member.guild, f"✅ Nuevo miembro: {member.mention} ({member.id}) - Instrucciones de verificación enviadas")
    except:
        pass

@bot.event
async def on_member_remove(member):
    """Cuando alguien se va del servidor"""
    await agregar_evento_real("👋", "MEMBER_REMOVE", f"{member.name} ({member.id})", member.guild)

@bot.event
async def on_guild_channel_create(channel):
    """Cuando se crea un canal"""
    await agregar_evento_real("➕", "CHANNEL_CREATE", f"{channel.name}", channel.guild)

@bot.event
async def on_guild_channel_delete(channel):
    """Cuando se elimina un canal"""
    await agregar_evento_real("➖", "CHANNEL_DELETE", f"{channel.name}", channel.guild)

@bot.event
async def on_guild_channel_update(before, after):
    """Cuando se edita un canal"""
    if before.name != after.name:
        await agregar_evento_real("✏️", "CHANNEL_UPDATE", f"{before.name} → {after.name}", before.guild)

@bot.event
async def on_guild_role_create(role):
    """Cuando se crea un rol"""
    await agregar_evento_real("🆕", "ROLE_CREATE", f"{role.name}", role.guild)

@bot.event
async def on_guild_role_delete(role):
    """Cuando se elimina un rol"""
    await agregar_evento_real("❌", "ROLE_DELETE", f"{role.name}", role.guild)

@bot.event
async def on_guild_role_update(before, after):
    """Cuando se edita un rol"""
    if before.name != after.name:
        await agregar_evento_real("🔧", "ROLE_UPDATE", f"{before.name} → {after.name}", before.guild)

@bot.event
async def on_message_delete(message):
    """Cuando se elimina un mensaje"""
    if not message.guild or message.author.bot:
        return
    
    try:
        contenido = message.content[:100] if message.content else "[sin texto]"
        canal_name = message.channel.mention if hasattr(message.channel, 'mention') else str(message.channel)
        detalles = f"Autor: {message.author.mention} | Contenido: `{contenido}` | Canal: {canal_name}"
        await agregar_evento_real("🗑️", "MESSAGE_DELETE", f"Mensaje de {message.author.name}", message.guild, detalles)
        print(f"✅ Mensaje eliminado: {message.author.name}")
    except Exception as e:
        print(f"Error en on_message_delete: {e}")

@bot.event
async def on_message_edit(before, after):
    """Cuando se edita un mensaje"""
    if before.author.bot or before.content == after.content:
        return
    
    detalles = f"Autor: {before.author.mention} | Antes: `{before.content[:100]}` | Después: `{after.content[:100]}`"
    await agregar_evento_real("✏️", "MESSAGE_EDIT", f"Mensaje editado", before.guild, detalles)

@bot.event
async def on_member_ban(guild, user):
    """Cuando alguien es baneado"""
    detalles = f"Usuario: {user.mention} ({user.id})"
    await agregar_evento_real("🚫", "MEMBER_BAN", f"{user.name} ha sido baneado", guild, detalles)

@bot.event
async def on_member_unban(guild, user):
    """Cuando se desbanea a alguien"""
    detalles = f"Usuario: {user.mention} ({user.id})"
    await agregar_evento_real("✅", "MEMBER_UNBAN", f"{user.name} ha sido desbaneado", guild, detalles)

@bot.event
async def on_voice_state_update(member, before, after):
    """Cuando alguien entra/sale de un canal de voz"""
    if before.channel is None and after.channel is not None:
        # Entró a voz
        detalles = f"Usuario: {member.mention} | Canal: {after.channel.name}"
        await agregar_evento_real("🎤", "VOICE_CHANNEL_JOIN", f"{member.name} entró a voz", member.guild, detalles)
    elif before.channel is not None and after.channel is None:
        # Salió de voz
        detalles = f"Usuario: {member.mention} | Canal: {before.channel.name}"
        await agregar_evento_real("🔇", "VOICE_CHANNEL_LEAVE", f"{member.name} salió de voz", member.guild, detalles)
    elif before.channel != after.channel:
        # Cambió de canal de voz
        detalles = f"Usuario: {member.mention} | De: {before.channel.name} → A: {after.channel.name}"
        await agregar_evento_real("🎧", "VOICE_CHANNEL_MOVE", f"{member.name} cambió de canal", member.guild, detalles)

async def verificar_mensajes_eliminados():
    """Tarea background que verifica regularmente el audit log"""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            for guild in bot.guilds:
                if guild.id in mensajes_cache and mensajes_cache[guild.id]:
                    # Verificar cada 5 segundos
                    await asyncio.sleep(5)
        except:
            pass
        await asyncio.sleep(5)

@bot.event
async def on_ready():
    print(f"Bot iniciado como {bot.user}")
    
    # Sincronizar slash commands
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} slash commands sincronizados")
    except Exception as e:
        print(f"Error sincronizando slash commands: {e}")
    
    # Iniciar tarea background de verificación de eliminaciones
    if not bot.get_cog("BackgroundTasks"):
        bot.loop.create_task(verificar_mensajes_eliminados())
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("SELECT usuario_id, COUNT(*) as total_warns FROM advertencias_log GROUP BY usuario_id")
        advertencias_db = cur.fetchall()
        for row in advertencias_db:
            advertencias[row[0]] = row[1]
        
        cur.execute("SELECT usuario_id, COUNT(*) as total_mutes FROM muteos_log GROUP BY usuario_id")
        muteos_db = cur.fetchall()
        for row in muteos_db:
            toxicidad_puntos[row[0]] = row[1]
        
        cur.execute("SELECT usuario_id FROM shadowmute_log WHERE activo = true")
        shadowmute_db = cur.fetchall()
        for row in shadowmute_db:
            shadowmuted.add(row[0])
        
        cur.close()
        conn.close()
        print("✅ Datos cargados desde la base de datos")
    except Exception as e:
        print(f"⚠️ No se pudo cargar datos de la BD: {e}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    autor = message.author
    guild = message.guild
    contenido = message.content.lower()
    referencia_id = message.reference.resolved.author.id if message.reference else None

    # --- DETECCIÓN DE MENCIÓN DEL BOT ---
    if bot.user in message.mentions:
        embed = discord.Embed(
            title="🤖 Hola, soy un bot de moderación",
            description="Estoy aquí para mantener tu servidor seguro y organizado.\n\n"
                       "**Mis características principales:**\n"
                       "✅ Detección automática de toxicidad\n"
                       "✅ Sistema de advertencias progresivas\n"
                       "✅ Muteos automáticos\n"
                       "✅ Estadísticas del servidor\n"
                       "✅ Logs en tiempo real\n\n"
                       "**Usa `?help` para ver todos los comandos disponibles**",
            color=discord.Color.purple()
        )
        embed.set_thumbnail(url=bot.user.display_avatar.url)
        embed.set_footer(text="Creado por AYATSS")
        await message.reply(embed=embed, mention_author=False)
        # No procesar más si fue solo una mención
        if contenido.strip() == f"<@{bot.user.id}>".lower() or contenido.strip() == f"<@!{bot.user.id}>".lower():
            return

    # --- SHADOWMUTE ---
    if autor.id in shadowmuted:
        await message.delete()
        return

    # Rastrear mensajes enviados
    mensajes_enviados[autor.id] += 1
    
    # Rastrear mensaje en cache para detectar eliminaciones
    if guild:
        mensajes_cache[guild.id][message.id] = (autor.mention, message.content[:100] if message.content else "[sin texto]", discord.utils.utcnow())

    # --- DETECCIÓN DE SPAM ---
    es_spam, tipo_spam = detectar_spam(message)
    if es_spam:
        # Si ya fue muteado antes, aplicar mute directo sin advertencias
        if toxicidad_puntos[autor.id] > 0:
            toxicidad_puntos[autor.id] += 1
            puntos = toxicidad_puntos[autor.id]
            
            if puntos == 1: tiempo = 30
            elif puntos == 2: tiempo = 300
            elif puntos == 3: tiempo = 900
            else: tiempo = 3600
            
            await enviar_log(guild, f"🔇 MUTEO POR SPAM (REINCIDENTE) | Usuario: {autor.mention} ({autor.id}) | Razón: {tipo_spam} | Puntos: {puntos} | Silencio: {tiempo}s | Canal: {message.channel.mention}")
            await silenciar_usuario(autor, guild, tiempo, tipo_spam, message.id)
        else:
            # Primera vez: seguir el sistema de advertencias normales
            warns = await advertir_usuario(autor, guild, tipo_spam, message.channel)
            
            # Si superó el límite de advertencias, aplicar muteo
            if warns > ADVERTENCIAS_MAX:
                toxicidad_puntos[autor.id] += 1
                puntos = toxicidad_puntos[autor.id]
                
                if puntos == 1: tiempo = 30
                elif puntos == 2: tiempo = 300
                elif puntos == 3: tiempo = 900
                else: tiempo = 3600
                
                await enviar_log(guild, f"🔇 MUTEO POR SPAM | Usuario: {autor.mention} ({autor.id}) | Razón: {tipo_spam} | Advertencias: {warns} | Silencio: {tiempo}s | Canal: {message.channel.mention}")
                await silenciar_usuario(autor, guild, tiempo, tipo_spam, message.id)
        
        return

    # --- DETECCIÓN DE INSULTOS / PELEAS ---
    # Si es moderador, owner o admin, EXENTO de detección de toxicidad
    if not es_moderador_inmune(autor):
        es_toxico, es_insulto = detectar_pelea(contenido, autor.id, referencia_id)
        if es_toxico:
            if referencia_id:
                ultimo_insulto[autor.id] = referencia_id

            # Si ya fue muteado antes, aplicar mute directo sin advertencias
            if toxicidad_puntos[autor.id] > 0:
                toxicidad_puntos[autor.id] += 1
                puntos = toxicidad_puntos[autor.id]
                
                if puntos == 1: tiempo = 30
                elif puntos == 2: tiempo = 300
                elif puntos == 3: tiempo = 900
                else: tiempo = 3600
                
                await enviar_log(guild, f"🔇 MUTEO POR TOXICIDAD (REINCIDENTE) | Usuario: {autor.mention} ({autor.id}) | Mensaje: {contenido} | Puntos: {puntos} | Silencio: {tiempo}s | Canal: {message.channel.mention}")
                await silenciar_usuario(autor, guild, tiempo, "Comportamiento tóxico/lenguaje inapropiado", message.id)
            else:
                # Primera vez: seguir el sistema de advertencias normales
                warns = await advertir_usuario(autor, guild, "Comportamiento tóxico/lenguaje inapropiado", message.channel)
                
                # Si superó el límite de advertencias, aplicar muteo
                if warns > ADVERTENCIAS_MAX:
                    toxicidad_puntos[autor.id] += 1
                    puntos = toxicidad_puntos[autor.id]
                    
                    if puntos == 1: tiempo = 30
                    elif puntos == 2: tiempo = 300
                    elif puntos == 3: tiempo = 900
                    else: tiempo = 3600
                    
                    await enviar_log(guild, f"🔇 MUTEO POR TOXICIDAD | Usuario: {autor.mention} ({autor.id}) | Mensaje: {contenido} | Advertencias: {warns} | Silencio: {tiempo}s | Canal: {message.channel.mention}")
                    await silenciar_usuario(autor, guild, tiempo, "Comportamiento tóxico/lenguaje inapropiado", message.id)
            
            return
    
    # Procesar comandos
    await bot.process_commands(message)

# ----- COMANDOS DE MODERADOR -----
@bot.command()
@commands.has_permissions(manage_messages=True)
async def resetpuntos(ctx, usuario: discord.Member):
    toxicidad_puntos[usuario.id] = 0
    await ctx.send(f"🧹 Puntos de toxicidad de {usuario.mention} reiniciados.")
    await enviar_log(ctx.guild, f"🔄 Puntos de toxicidad reiniciados para {usuario}.")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def calmar(ctx):
    await ctx.send("🕊️ Modo calma activado. Bajemos la tensión en el canal.")
    await enviar_log(ctx.guild, f"🕊️ Modo calma activado por {ctx.author} en {ctx.channel.mention}.")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def desmutear(ctx, usuario: discord.Member):
    rol = get(ctx.guild.roles, name=SILENCE_ROLE_NAME)
    if rol and rol in usuario.roles:
        await usuario.remove_roles(rol)
        await ctx.send(f"🔊 {usuario.mention} ha sido desmuteado por {ctx.author.mention}.")
        await enviar_log(ctx.guild, f"🔊 Usuario {usuario} ({usuario.id}) desmuteado manualmente por {ctx.author} en {ctx.channel.mention}.")
    else:
        await ctx.send(f"❌ {usuario.mention} no está silenciado.")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def verwarns(ctx, usuario: discord.Member):
    warns = advertencias[usuario.id]
    await ctx.send(f"📊 {usuario.mention} tiene **{warns}** advertencia(s) de {ADVERTENCIAS_MAX}.")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def resetwarns(ctx, usuario: discord.Member):
    advertencias[usuario.id] = 0
    await ctx.send(f"🧹 Advertencias de {usuario.mention} reiniciadas.")
    await enviar_log(ctx.guild, f"🔄 Advertencias reiniciadas para {usuario} por {ctx.author}.")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def estadisticas(ctx):
    embed = discord.Embed(title="📊 Estadísticas del Servidor", color=discord.Color.blue())
    
    # Top 5 usuarios con más advertencias
    top_warns = sorted(advertencias.items(), key=lambda x: x[1], reverse=True)[:5]
    warns_text = "\n".join([f"<@{uid}>: **{warns}** warns" for uid, warns in top_warns if warns > 0]) or "Ninguna advertencia registrada"
    embed.add_field(name="🚨 Top Advertencias", value=warns_text, inline=False)
    
    # Top 5 usuarios con más puntos de toxicidad
    top_toxicos = sorted(toxicidad_puntos.items(), key=lambda x: x[1], reverse=True)[:5]
    toxicos_text = "\n".join([f"<@{uid}>: **{puntos}** puntos" for uid, puntos in top_toxicos if puntos > 0]) or "Ningún punto de toxicidad"
    embed.add_field(name="🔥 Top Toxicidad", value=toxicos_text, inline=False)
    
    # Estadísticas generales
    total_warns = sum(advertencias.values())
    total_toxicos = sum(toxicidad_puntos.values())
    embed.add_field(name="📈 Totales", value=f"**Advertencias:** {total_warns}\n**Puntos toxicidad:** {total_toxicos}", inline=False)
    
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def infousuario(ctx, usuario: discord.Member):
    embed = discord.Embed(title=f"👤 Información de {usuario.name}", color=discord.Color.green())
    embed.set_thumbnail(url=usuario.display_avatar.url)
    
    # Información básica
    embed.add_field(name="📝 Nombre", value=usuario.display_name, inline=True)
    embed.add_field(name="🆔 ID", value=usuario.id, inline=True)
    embed.add_field(name="📅 Cuenta creada", value=usuario.created_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name="📆 Se unió al servidor", value=usuario.joined_at.strftime("%d/%m/%Y") if usuario.joined_at else "Desconocido", inline=True)
    
    # Estadísticas de moderación
    warns = advertencias[usuario.id]
    puntos = toxicidad_puntos[usuario.id]
    enviados = mensajes_enviados[usuario.id]
    
    embed.add_field(name="⚠️ Advertencias", value=f"{warns}/{ADVERTENCIAS_MAX}", inline=True)
    embed.add_field(name="🔥 Puntos de toxicidad", value=str(puntos), inline=True)
    embed.add_field(name="📨 Mensajes enviados", value=str(enviados), inline=True)
    
    # Roles
    roles = [role.mention for role in usuario.roles if role.name != "@everyone"]
    embed.add_field(name=f"🎭 Roles ({len(roles)})", value=" ".join(roles) if roles else "Sin roles", inline=False)
    
    await ctx.send(embed=embed)

class TituloModal(discord.ui.Modal):
    def __init__(self, current_value="", parent_view=None):
        super().__init__(title="Editar Título")
        self.parent_view = parent_view
        self.add_item(discord.ui.TextInput(
            label="Título",
            placeholder="Ingresa el título",
            default=current_value,
            max_length=256,
            required=False
        ))
    
    async def on_submit(self, interaction: discord.Interaction):
        valor = self.children[0].value.strip() if self.children[0].value else ""
        self.parent_view.embed_data["title"] = valor or "Sin título"
        await interaction.response.defer()
        await self.parent_view.actualizar_preview()

class DescripcionModal(discord.ui.Modal):
    def __init__(self, current_value="", parent_view=None):
        super().__init__(title="Editar Descripción")
        self.parent_view = parent_view
        self.add_item(discord.ui.TextInput(
            label="Descripción (máx. 200 palabras)",
            placeholder="Ingresa la descripción",
            default=current_value,
            max_length=1000,
            required=False
        ))
    
    async def on_submit(self, interaction: discord.Interaction):
        valor = self.children[0].value.strip() if self.children[0].value else ""
        self.parent_view.embed_data["description"] = valor
        await interaction.response.defer()
        await self.parent_view.actualizar_preview()

class ColorModal(discord.ui.Modal):
    def __init__(self, parent_view=None):
        super().__init__(title="Editar Color")
        self.parent_view = parent_view
        self.add_item(discord.ui.TextInput(
            label="Color",
            placeholder="blue/red/green/yellow/purple/orange/gold",
            default="blue",
            max_length=10,
            required=False
        ))
    
    async def on_submit(self, interaction: discord.Interaction):
        valor = self.children[0].value.strip().lower() if self.children[0].value else "blue"
        colores = {
            "blue": discord.Color.blue(),
            "red": discord.Color.red(),
            "green": discord.Color.green(),
            "yellow": discord.Color.from_rgb(255, 255, 0),
            "purple": discord.Color.purple(),
            "orange": discord.Color.orange(),
            "gold": discord.Color.gold()
        }
        self.parent_view.embed_data["color"] = colores.get(valor, discord.Color.blue())
        await interaction.response.defer()
        await self.parent_view.actualizar_preview()

class ImagenModal(discord.ui.Modal):
    def __init__(self, current_value="", parent_view=None):
        super().__init__(title="Editar Imagen")
        self.parent_view = parent_view
        self.add_item(discord.ui.TextInput(
            label="URL Imagen",
            placeholder="https://ejemplo.com/imagen.png",
            default=current_value,
            max_length=256,
            required=False
        ))
    
    async def on_submit(self, interaction: discord.Interaction):
        valor = self.children[0].value.strip() if self.children[0].value else ""
        self.parent_view.embed_data["image_url"] = valor if valor else None
        await interaction.response.defer()
        await self.parent_view.actualizar_preview()

class EmbedEditorView(discord.ui.View):
    def __init__(self, embed_data, autor, canal, message):
        super().__init__(timeout=300)
        self.embed_data = embed_data
        self.autor = autor
        self.canal = canal
        self.message = message
    
    async def actualizar_preview(self):
        embed_preview = discord.Embed(
            title=self.embed_data.get("title", "Sin título"),
            description=self.embed_data.get("description", ""),
            color=self.embed_data.get("color", discord.Color.blue())
        )
        if self.embed_data.get("image_url"):
            embed_preview.set_image(url=self.embed_data["image_url"])
        embed_preview.set_footer(text="Click en los botones para editar")
        try:
            await self.message.edit(embed=embed_preview)
        except Exception as e:
            print(f"Error actualizando preview: {e}")
    
    @discord.ui.button(label="📝 Título", style=discord.ButtonStyle.primary)
    async def edit_titulo(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.autor:
            await interaction.response.defer()
            return
        modal = TituloModal(self.embed_data.get("title", ""), self)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="📄 Descripción", style=discord.ButtonStyle.primary)
    async def edit_descripcion(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.autor:
            await interaction.response.defer()
            return
        modal = DescripcionModal(self.embed_data.get("description", ""), self)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="🎨 Color", style=discord.ButtonStyle.success)
    async def edit_color(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.autor:
            await interaction.response.defer()
            return
        modal = ColorModal(self)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="🖼️ Imagen", style=discord.ButtonStyle.success)
    async def edit_imagen(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.autor:
            await interaction.response.defer()
            return
        modal = ImagenModal(self.embed_data.get("image_url", ""), self)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="✅ Publicar", style=discord.ButtonStyle.green, row=1)
    async def publicar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.autor:
            await interaction.response.defer()
            return
        embed_final = discord.Embed(
            title=self.embed_data.get("title", "Sin título"),
            description=self.embed_data.get("description", ""),
            color=self.embed_data.get("color", discord.Color.blue())
        )
        if self.embed_data.get("image_url"):
            try:
                embed_final.set_image(url=self.embed_data["image_url"])
            except:
                pass
        embed_final.set_footer(text=f"Publicado por {self.autor.name}", icon_url=self.autor.display_avatar.url)
        await interaction.response.defer()
        await self.canal.send(embed=embed_final)
        await self.message.delete()
        await enviar_log(self.canal.guild, f"📢 Embed publicado por {self.autor.mention}")
    
    @discord.ui.button(label="❌ Cancelar", style=discord.ButtonStyle.red, row=1)
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.autor:
            await interaction.response.defer()
            return
        await interaction.response.defer()
        await self.message.delete()

@bot.command()
async def listmute(ctx):
    """Ver todos los mutes que ha hecho el bot"""
    if not any(mute_historial.values()):
        await ctx.send("✅ No hay registro de mutes")
        return
    
    embed = discord.Embed(title="🔇 Registro de Todos los Mutes", color=discord.Color.red())
    
    total_mutes = 0
    registro_texto = ""
    
    for usuario_id, muteos in mute_historial.items():
        if muteos:
            total_mutes += len(muteos)
            registro_texto += f"\n**<@{usuario_id}>** - {len(muteos)} mute(s)\n"
            for i, mute_info in enumerate(muteos, 1):
                if isinstance(mute_info, tuple):
                    fecha = mute_info[0]
                    duracion = mute_info[1]
                    razon = mute_info[2] if len(mute_info) > 2 else "Sin especificar"
                    msg_id = mute_info[3] if len(mute_info) > 3 else None
                else:
                    continue
                
                minutos = duracion // 60
                if minutos >= 60:
                    tiempo_str = f"{minutos // 60}h {minutos % 60}m"
                else:
                    tiempo_str = f"{minutos}m"
                
                msg_info = f"[ID: {msg_id}]" if msg_id else ""
                registro_texto += f"  {i}. {fecha} ({tiempo_str})\n      Razón: {razon} {msg_info}\n"
    
    if len(registro_texto) > 4096:
        embed.add_field(name=f"Total Mutes: {total_mutes}", value=registro_texto[:4000] + "...", inline=False)
    else:
        embed.add_field(name=f"Total Mutes: {total_mutes}", value=registro_texto, inline=False)
    
    await ctx.send(embed=embed)

@bot.command()
async def topusuarios(ctx):
    """Muestra los usuarios más activos y con más advertencias"""
    embed = discord.Embed(title="🏆 TOP USUARIOS", color=discord.Color.gold())
    
    top_activos = sorted(mensajes_enviados.items(), key=lambda x: x[1], reverse=True)[:5]
    activos_text = "\n".join([f"<@{uid}>: **{msgs}** mensajes" for uid, msgs in top_activos if msgs > 0]) or "Sin datos"
    embed.add_field(name="📨 Más Activos", value=activos_text, inline=False)
    
    top_warns = sorted(advertencias.items(), key=lambda x: x[1], reverse=True)[:5]
    warns_text = "\n".join([f"<@{uid}>: **{warns}** advertencias" for uid, warns in top_warns if warns > 0]) or "Sin advertencias"
    embed.add_field(name="⚠️ Más Advertencias", value=warns_text, inline=False)
    
    await ctx.send(embed=embed)

@bot.command()
async def mutehistorial(ctx, usuario: discord.Member):
    """Muestra el historial de muteos de un usuario"""
    if not mute_historial[usuario.id]:
        await ctx.send(f"✅ {usuario.mention} no tiene registro de muteos.")
        return
    
    embed = discord.Embed(title=f"🔇 Historial de Muteos - {usuario.name}", color=discord.Color.red())
    embed.set_thumbnail(url=usuario.display_avatar.url)
    
    historial_texto = ""
    for i, (fecha, duracion) in enumerate(mute_historial[usuario.id], 1):
        minutos = duracion // 60
        if minutos >= 60:
            tiempo_str = f"{minutos // 60}h {minutos % 60}m"
        else:
            tiempo_str = f"{minutos}m"
        historial_texto += f"{i}. **{fecha}** - Duración: {tiempo_str}\n"
    
    embed.add_field(name=f"Total de Muteos: {len(mute_historial[usuario.id])}", value=historial_texto, inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def report(ctx, usuario: discord.Member, *, motivo: str):
    """Reportar a un usuario por comportamiento tóxico"""
    if usuario == ctx.author:
        await ctx.send("❌ No puedes reportarte a ti mismo.")
        return
    
    if usuario.bot:
        await ctx.send("❌ No puedes reportar a un bot.")
        return
    
    fecha = discord.utils.utcnow().strftime("%d/%m/%Y %H:%M:%S")
    reportes.append((ctx.author, usuario, motivo, fecha))
    
    # Guardar en BD
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO reportes_log (reportador_id, reportador_nombre, reportado_id, reportado_nombre, motivo, guild_id) VALUES (%s, %s, %s, %s, %s, %s)",
            (ctx.author.id, ctx.author.name, usuario.id, usuario.name, motivo, ctx.guild.id)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error guardando reporte en BD: {e}")
    
    embed = discord.Embed(title="📋 NUEVO REPORTE", color=discord.Color.orange())
    embed.add_field(name="🚨 Reportado", value=usuario.mention, inline=False)
    embed.add_field(name="👤 Reportador", value=ctx.author.mention, inline=False)
    embed.add_field(name="📝 Motivo", value=motivo, inline=False)
    embed.add_field(name="📅 Fecha", value=fecha, inline=False)
    embed.set_footer(text=f"Total de reportes: {len(reportes)}")
    
    canal_mod = get(ctx.guild.text_channels, name="mod-logs")
    if canal_mod:
        await canal_mod.send(embed=embed)
    
    await ctx.send(f"✅ Reporte enviado. Gracias por ayudar a mantener el servidor seguro.")
    await enviar_log(ctx.guild, f"📋 Reporte: {ctx.author.mention} reportó a {usuario.mention} - Motivo: {motivo}")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def listreport(ctx):
    """Lista todos los reportes con paginación"""
    if not reportes:
        await ctx.send("✅ No hay reportes registrados.")
        return
    
    reportes_por_pagina = 5
    total_paginas = (len(reportes) + reportes_por_pagina - 1) // reportes_por_pagina
    pagina_actual = 0
    
    def crear_embed(pagina):
        inicio = pagina * reportes_por_pagina
        fin = inicio + reportes_por_pagina
        reporte_set = reportes[inicio:fin]
        
        embed = discord.Embed(title="📋 LISTA DE REPORTES", color=discord.Color.orange())
        
        for i, (reportador, reportado, motivo, fecha) in enumerate(reporte_set, 1 + inicio):
            embed.add_field(
                name=f"#{i} - {reportado.name}",
                value=f"👤 **Reportador:** {reportador.mention}\n"
                      f"📝 **Motivo:** {motivo}\n"
                      f"📅 **Fecha:** {fecha}",
                inline=False
            )
        
        embed.set_footer(text=f"Página {pagina + 1}/{total_paginas} | Total: {len(reportes)} reportes")
        return embed
    
    mensaje = await ctx.send(embed=crear_embed(pagina_actual))
    
    if total_paginas > 1:
        await mensaje.add_reaction("◀️")
        await mensaje.add_reaction("▶️")
        
        def check(reaction, usuario):
            return usuario == ctx.author and reaction.message.id == mensaje.id and str(reaction.emoji) in ["◀️", "▶️"]
        
        while True:
            try:
                reaction, usuario = await bot.wait_for("reaction_add", timeout=60.0, check=check)
                
                if str(reaction.emoji) == "▶️" and pagina_actual < total_paginas - 1:
                    pagina_actual += 1
                elif str(reaction.emoji) == "◀️" and pagina_actual > 0:
                    pagina_actual -= 1
                
                await mensaje.edit(embed=crear_embed(pagina_actual))
                await reaction.remove(usuario)
                
            except asyncio.TimeoutError:
                await mensaje.clear_reactions()
                break

@bot.command()
@commands.has_permissions(manage_messages=True)
async def listwarn(ctx, usuario: discord.Member = None):
    """Ver historial de todas las advertencias de un usuario desde la BD"""
    try:
        if usuario is None:
            await ctx.send("❌ Debes mencionar a un usuario. Uso: `?listwarn @usuario`")
            return
        
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT fecha, razon, numero_advertencia FROM advertencias_log WHERE usuario_id = %s ORDER BY fecha DESC",
            (usuario.id,)
        )
        advertencias_db = cur.fetchall()
        cur.close()
        conn.close()
        
        if not advertencias_db:
            await ctx.send(f"✅ {usuario.mention} no tiene advertencias registradas.")
            return
        
        embed = discord.Embed(title=f"📋 Historial de Advertencias - {usuario.name}", color=discord.Color.blue())
        embed.set_thumbnail(url=usuario.display_avatar.url)
        
        historial_texto = ""
        for adv in advertencias_db:
            fecha = adv['fecha'].strftime("%d/%m/%Y %H:%M")
            historial_texto += f"**#{adv['numero_advertencia']}** - {fecha}\n__{adv['razon']}__\n\n"
        
        if len(historial_texto) > 2048:
            embed.add_field(name=f"Total de Advertencias: {len(advertencias_db)}", value=historial_texto[:2048] + "...", inline=False)
        else:
            embed.add_field(name=f"Total de Advertencias: {len(advertencias_db)}", value=historial_texto, inline=False)
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f"❌ Error: {str(e)}")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def shadowmute(ctx, usuario: discord.Member):
    """Aplicar shadowmute a un usuario (ve sus mensajes pero solo él los ve)"""
    if usuario.id in shadowmuted:
        await ctx.send(f"❌ {usuario.mention} ya está en shadowmute.")
        return
    
    shadowmuted.add(usuario.id)
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO shadowmute_log (usuario_id, usuario_nombre, moderador_id, moderador_nombre, guild_id, activo) VALUES (%s, %s, %s, %s, %s, true)",
            (usuario.id, usuario.name, ctx.author.id, ctx.author.name, ctx.guild.id)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error guardando shadowmute en BD: {e}")
    
    await ctx.send(f"👻 {usuario.mention} está en **shadowmute**. Sus mensajes solo los verá él.")
    await enviar_log(ctx.guild, f"👻 SHADOWMUTE aplicado a {usuario.mention} ({usuario.id}) por {ctx.author.mention}")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def unshadowmute(ctx, usuario: discord.Member):
    """Remover shadowmute de un usuario"""
    if usuario.id not in shadowmuted:
        await ctx.send(f"❌ {usuario.mention} no está en shadowmute.")
        return
    
    shadowmuted.discard(usuario.id)
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE shadowmute_log SET activo = false WHERE usuario_id = %s AND guild_id = %s",
            (usuario.id, ctx.guild.id)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error actualizando shadowmute en BD: {e}")
    
    await ctx.send(f"🟢 {usuario.mention} ha sido removido del shadowmute.")
    await enviar_log(ctx.guild, f"🟢 SHADOWMUTE removido de {usuario.mention} ({usuario.id}) por {ctx.author.mention}")

class VerificacionModal(discord.ui.Modal, title="🔐 Verificación"):
    """Modal para ingresar el código de verificación"""
    codigo = discord.ui.TextInput(
        label="Código de Verificación",
        placeholder="Ingresa el código de 6 dígitos",
        min_length=6,
        max_length=6
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        usuario = interaction.user
        guild = interaction.guild
        codigo_ingresado = str(self.codigo).strip()
        
        if usuario.id not in codigos_verificacion:
            await interaction.response.send_message("❌ No tienes ningún código pendiente.", ephemeral=True)
            return
        
        if codigos_verificacion[usuario.id] != codigo_ingresado:
            await interaction.response.send_message("❌ Código incorrecto.", ephemeral=True)
            return
        
        rol_verificado = guild.get_role(1431669432387899583)
        if rol_verificado is None:
            await interaction.response.send_message("❌ No se pudo encontrar el rol de verificación.", ephemeral=True)
            return
        
        await usuario.add_roles(rol_verificado)
        
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "UPDATE verificacion_log SET verificado = true, fecha_verificacion = CURRENT_TIMESTAMP WHERE usuario_id = %s",
                (usuario.id,)
            )
            if cur.rowcount == 0:
                cur.execute(
                    "INSERT INTO verificacion_log (usuario_id, usuario_nombre, codigo_verificacion, verificado, guild_id) VALUES (%s, %s, %s, true, %s)",
                    (usuario.id, usuario.name, codigo_ingresado, guild.id)
                )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"Error guardando verificación en BD: {e}")
        
        codigos_verificacion.pop(usuario.id, None)
        
        embed = discord.Embed(
            title="✅ ¡Verificado!",
            description=f"Bienvenido a {guild.name}, {usuario.mention}",
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=usuario.display_avatar.url)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await enviar_log(guild, f"✅ VERIFICADO: {usuario.mention} ({usuario.id})")

class VerificacionView(discord.ui.View):
    def __init__(self):
        super().__init__()
    
    @discord.ui.button(label="✅ Verificarse", style=discord.ButtonStyle.green)
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        usuario = interaction.user
        guild = interaction.guild
        
        if usuario.id in codigos_verificacion:
            await interaction.response.send_message("❌ Ya tienes un código pendiente. Intenta de nuevo en unos momentos.", ephemeral=True)
            return
        
        rol_verificado = guild.get_role(1431669432387899583)
        if rol_verificado and rol_verificado in usuario.roles:
            await interaction.response.send_message("✅ Ya estás verificado en este servidor.", ephemeral=True)
            return
        
        codigo = ''.join(random.choices(string.digits, k=6))
        codigos_verificacion[usuario.id] = codigo
        
        embed = discord.Embed(
            title="🔐 Código de Verificación",
            description=f"Tu código de verificación es:\n\n`{codigo}`",
            color=discord.Color.blue()
        )
        embed.set_footer(text="El código expira en 5 minutos")
        
        try:
            await usuario.send(embed=embed)
            await interaction.response.send_message("✅ Código enviado a tu DM.\n👇 Pulsa el botón de abajo para ingresar el código:", view=VerificacionModalView(), ephemeral=True)
            await enviar_log(guild, f"🔐 Código de verificación enviado a {usuario.mention}")
        except:
            await interaction.response.send_message("❌ No puedo enviar mensajes privados. Abre tus DMs.", ephemeral=True)
            return
        
        async def eliminar_codigo():
            await asyncio.sleep(300)
            codigos_verificacion.pop(usuario.id, None)
        
        asyncio.create_task(eliminar_codigo())

class VerificacionModalView(discord.ui.View):
    def __init__(self):
        super().__init__()
    
    @discord.ui.button(label="Ingresar Código", style=discord.ButtonStyle.primary)
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VerificacionModal())

@bot.command()
@commands.is_owner()
async def setlogschannel(ctx, canal: discord.TextChannel):
    """Establece el canal personalizado para los logs en tiempo real (Solo Owner)"""
    guild = ctx.guild
    logs_channel_id[guild.id] = canal.id
    
    embed = discord.Embed(
        title="✅ Canal de Logs Configurado",
        description=f"Los eventos se enviarán a {canal.mention}",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)
    print(f"✅ Canal de logs configurado para {guild.name}: {canal.name} (ID: {canal.id})")

@bot.command()
@commands.is_owner()
async def verify(ctx):
    """Verificarse para acceder al servidor con botón interactivo (Solo Owner)"""
    guild = ctx.guild
    
    embed = discord.Embed(
        title="🔐 Verificación del Servidor",
        description="Haz clic en el botón de abajo para comenzar la verificación.",
        color=discord.Color.blue()
    )
    embed.set_footer(text="Tu seguridad es importante para nosotros")
    
    await ctx.send(embed=embed, view=VerificacionView())
    await enviar_log(guild, f"🔐 Sistema de verificación iniciado por {ctx.author.mention}")

@bot.command()
@commands.is_owner()
async def logs(ctx):
    """Ver registro en tiempo real del servidor (Solo Owner) - Se actualiza automáticamente"""
    
    if not eventos_tiempo_real:
        embed = discord.Embed(
            title="📋 Eventos en Tiempo Real",
            description="No hay eventos registrados aún.",
            color=discord.Color.greyple()
        )
        await ctx.send(embed=embed)
        return
    
    try:
        # Crear embed principal
        embed = discord.Embed(
            title="📋 Eventos en Tiempo Real del Servidor",
            description=f"Últimos {len(eventos_tiempo_real)} eventos capturados automáticamente",
            color=discord.Color.blue()
        )
        
        # Construir texto de eventos (en orden inverso para mostrar los más recientes primero)
        logs_texto = ""
        for evento in reversed(eventos_tiempo_real):
            emoji = evento["tipo"]
            tipo = evento["descripcion"]
            detalles = evento["detalles"]
            timestamp = evento["timestamp"]
            logs_texto += f"{emoji} **{tipo}** - {detalles}\n   {timestamp}\n"
        
        # Dividir el texto en chunks que respeten el límite de 1024 caracteres por field
        chunks = []
        current_chunk = ""
        
        for linea in logs_texto.split("\n"):
            if len(current_chunk) + len(linea) + 1 > 1020:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = linea + "\n"
            else:
                current_chunk += linea + "\n"
        
        if current_chunk:
            chunks.append(current_chunk)
        
        # Enviar embeds
        if len(chunks) <= 5:
            for i, chunk in enumerate(chunks, 1):
                field_name = "Eventos Recientes" if i == 1 else f"Continúa ({i})"
                embed.add_field(name=field_name, value=chunk, inline=False)
            embed.set_footer(text=f"⏱️ Se actualiza en tiempo real | {ctx.guild.name}")
            await ctx.send(embed=embed)
        else:
            embeds_list = []
            for chunk_idx in range(0, len(chunks), 5):
                chunk_group = chunks[chunk_idx:chunk_idx+5]
                parte_num = (chunk_idx // 5) + 1
                
                embed_parte = discord.Embed(
                    title=f"📋 Eventos en Tiempo Real (Parte {parte_num})",
                    color=discord.Color.blue()
                )
                
                for i, chunk in enumerate(chunk_group, 1):
                    field_name = f"Eventos {(chunk_idx + i)}" if i > 1 else "Eventos Recientes"
                    embed_parte.add_field(name=field_name, value=chunk, inline=False)
                
                if chunk_idx + 5 >= len(chunks):
                    embed_parte.set_footer(text=f"⏱️ Se actualiza en tiempo real | {ctx.guild.name}")
                
                embeds_list.append(embed_parte)
            
            for embed_to_send in embeds_list:
                await ctx.send(embed=embed_to_send)
    
    except Exception as e:
        print(f"Error en comando logs: {e}")
        embed = discord.Embed(
            title="❌ Error",
            description=f"Error al obtener los eventos: {str(e)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

@bot.command(name="help")
async def help_command(ctx):
    """Muestra todos los comandos disponibles"""
    embed = discord.Embed(title="📚 COMANDOS DEL BOT", color=discord.Color.blurple())
    
    embed.add_field(
        name="👤 Comandos de Usuario",
        value="`?verify` - Verificarse presionando un botón (recibirás código por DM)\n"
              "`?embed` - Crear un embed interactivo para anuncios\n"
              "`?report @usuario motivo` - Reportar usuario tóxico",
        inline=False
    )
    
    embed.add_field(
        name="🛡️ Comandos de Moderador",
        value="`?estadisticas` - Ver stats del servidor\n"
              "`?infousuario @usuario` - Info completa de usuario\n"
              "`?verwarns @usuario` - Ver advertencias de usuario\n"
              "`?resetwarns @usuario` - Reiniciar advertencias\n"
              "`?resetpuntos @usuario` - Reiniciar puntos de toxicidad\n"
              "`?desmutear @usuario` - Quitar muteo manual\n"
              "`?shadowmute @usuario` - Aplicar shadowmute (solo ve sus mensajes)\n"
              "`?unshadowmute @usuario` - Remover shadowmute\n"
              "`?calmar` - Activar modo calma\n"
              "`?topusuarios` - Top usuarios activos\n"
              "`?mutehistorial @usuario` - Historial de muteos\n"
              "`?listwarn @usuario` - Historial de advertencias\n"
              "`?listreport` - Lista de reportes (con paginación)\n"
              "`?logs` - Ver registro de auditoría del servidor (Solo Owner)\n"
              "`?help` - Ver este menú",
        inline=False
    )
    
    embed.set_footer(text="Prefijo: ? | Usa ?help para más información")
    await ctx.send(embed=embed)

# ----- SLASH COMMANDS -----
@bot.tree.command(name="help", description="Muestra todos los comandos disponibles")
async def slash_help(interaction: discord.Interaction):
    """Slash command de ayuda"""
    embed = discord.Embed(title="📚 COMANDOS DEL BOT", color=discord.Color.blurple())
    
    embed.add_field(
        name="👤 Comandos de Usuario",
        value="`/verify` - Verificarse presionando un botón\n"
              "`/estadisticas` - Ver stats del servidor\n"
              "`/help` - Ver este menú",
        inline=False
    )
    
    embed.add_field(
        name="🛡️ Comandos de Moderador",
        value="`/verwarns @usuario` - Ver advertencias\n"
              "`/resetwarns @usuario` - Reiniciar advertencias\n"
              "`/desmutear @usuario` - Quitar muteo\n"
              "`/topusuarios` - Top usuarios activos",
        inline=False
    )
    
    embed.set_footer(text="✨ ¡Escribe / para ver más comandos!")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="estadisticas", description="Ver estadísticas del servidor")
async def slash_estadisticas(interaction: discord.Interaction):
    """Slash command de estadísticas"""
    embed = discord.Embed(title="📊 Estadísticas del Servidor", color=discord.Color.blue())
    
    top_warns = sorted(advertencias.items(), key=lambda x: x[1], reverse=True)[:5]
    warns_text = "\n".join([f"<@{uid}>: **{warns}** warns" for uid, warns in top_warns if warns > 0]) or "Ninguna"
    embed.add_field(name="🚨 Top Advertencias", value=warns_text, inline=False)
    
    top_toxicos = sorted(toxicidad_puntos.items(), key=lambda x: x[1], reverse=True)[:5]
    toxicos_text = "\n".join([f"<@{uid}>: **{puntos}** puntos" for uid, puntos in top_toxicos if puntos > 0]) or "Ninguno"
    embed.add_field(name="☠️ Top Toxicidad", value=toxicos_text, inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="topusuarios", description="Ver top usuarios más activos y con más advertencias")
async def slash_topusuarios(interaction: discord.Interaction):
    embed = discord.Embed(title="🏆 TOP USUARIOS", color=discord.Color.gold())
    
    top_activos = sorted(mensajes_enviados.items(), key=lambda x: x[1], reverse=True)[:5]
    activos_text = "\n".join([f"<@{uid}>: **{msgs}** mensajes" for uid, msgs in top_activos if msgs > 0]) or "Sin datos"
    embed.add_field(name="📨 Más Activos", value=activos_text, inline=False)
    
    top_warns = sorted(advertencias.items(), key=lambda x: x[1], reverse=True)[:5]
    warns_text = "\n".join([f"<@{uid}>: **{warns}** advertencias" for uid, warns in top_warns if warns > 0]) or "Sin advertencias"
    embed.add_field(name="⚠️ Más Advertencias", value=warns_text, inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="mutehistorial", description="Ver historial de muteos de un usuario")
async def slash_mutehistorial(interaction: discord.Interaction, usuario: discord.User):
    if not mute_historial[usuario.id]:
        await interaction.response.send_message(f"✅ {usuario.mention} no tiene registro de muteos.", ephemeral=True)
        return
    
    embed = discord.Embed(title=f"🔇 Historial de Muteos - {usuario.name}", color=discord.Color.red())
    
    historial_texto = ""
    for i, (fecha, duracion) in enumerate(mute_historial[usuario.id], 1):
        minutos = duracion // 60
        if minutos >= 60:
            tiempo_str = f"{minutos // 60}h {minutos % 60}m"
        else:
            tiempo_str = f"{minutos}m"
        historial_texto += f"{i}. **{fecha}** - Duración: {tiempo_str}\n"
    
    embed.add_field(name=f"Total de Muteos: {len(mute_historial[usuario.id])}", value=historial_texto, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="report", description="Reportar a un usuario por comportamiento tóxico")
async def slash_report(interaction: discord.Interaction, usuario: discord.User, motivo: str):
    if usuario == interaction.user:
        await interaction.response.send_message("❌ No puedes reportarte a ti mismo.", ephemeral=True)
        return
    
    if usuario.bot:
        await interaction.response.send_message("❌ No puedes reportar a un bot.", ephemeral=True)
        return
    
    fecha = discord.utils.utcnow().strftime("%d/%m/%Y %H:%M:%S")
    guild_obj = interaction.guild
    miembro = guild_obj.get_member(usuario.id)
    reportes.append((interaction.user, miembro or usuario, motivo, fecha))
    
    embed = discord.Embed(title="📋 NUEVO REPORTE", color=discord.Color.orange())
    embed.add_field(name="🚨 Reportado", value=usuario.mention, inline=False)
    embed.add_field(name="👤 Reportador", value=interaction.user.mention, inline=False)
    embed.add_field(name="📝 Motivo", value=motivo, inline=False)
    embed.add_field(name="📅 Fecha", value=fecha, inline=False)
    
    canal_mod = get(guild_obj.text_channels, name="mod-logs")
    if canal_mod:
        await canal_mod.send(embed=embed)
    
    await interaction.response.send_message(f"✅ Reporte enviado. Gracias por ayudar a mantener el servidor seguro.", ephemeral=True)
    await enviar_log(guild_obj, f"📋 Reporte: {interaction.user.mention} reportó a {usuario.mention} - Motivo: {motivo}")

@bot.tree.command(name="infousuario", description="Ver información completa de un usuario")
async def slash_infousuario(interaction: discord.Interaction, usuario: discord.User):
    guild = interaction.guild
    miembro = guild.get_member(usuario.id)
    if not miembro:
        await interaction.response.send_message(f"❌ {usuario.mention} no está en el servidor.", ephemeral=True)
        return
    
    embed = discord.Embed(title=f"👤 Información de {usuario.name}", color=discord.Color.green())
    embed.set_thumbnail(url=usuario.display_avatar.url)
    
    embed.add_field(name="📝 Nombre", value=usuario.display_name, inline=True)
    embed.add_field(name="🆔 ID", value=usuario.id, inline=True)
    embed.add_field(name="📅 Cuenta creada", value=usuario.created_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name="📆 Se unió al servidor", value=miembro.joined_at.strftime("%d/%m/%Y") if miembro.joined_at else "Desconocido", inline=True)
    
    warns = advertencias[usuario.id]
    puntos = toxicidad_puntos[usuario.id]
    enviados = mensajes_enviados[usuario.id]
    
    embed.add_field(name="⚠️ Advertencias", value=f"{warns}/{ADVERTENCIAS_MAX}", inline=True)
    embed.add_field(name="🔥 Puntos de toxicidad", value=str(puntos), inline=True)
    embed.add_field(name="📨 Mensajes enviados", value=str(enviados), inline=True)
    
    roles = [role.mention for role in miembro.roles if role.name != "@everyone"]
    embed.add_field(name=f"🎭 Roles ({len(roles)})", value=" ".join(roles) if roles else "Sin roles", inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.command()
async def serverinfo(ctx):
    """Ver información del servidor"""
    guild = ctx.guild
    
    embed = discord.Embed(title=f"🏛️ Información de {guild.name}", color=discord.Color.blue())
    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
    
    # Información básica
    embed.add_field(name="🆔 ID del Servidor", value=str(guild.id), inline=True)
    embed.add_field(name="👑 Owner", value=guild.owner.mention if guild.owner else "Desconocido", inline=True)
    embed.add_field(name="📅 Creado", value=guild.created_at.strftime("%d/%m/%Y %H:%M"), inline=True)
    
    # Estadísticas
    embed.add_field(name="👥 Miembros", value=f"{guild.member_count} total", inline=True)
    embed.add_field(name="📝 Canales", value=f"{len(guild.channels)} canales", inline=True)
    embed.add_field(name="🎭 Roles", value=f"{len(guild.roles)} roles", inline=True)
    
    # Más detalles
    embed.add_field(name="⚡ Nivel de Verificación", value=str(guild.verification_level).title(), inline=True)
    embed.add_field(name="🎨 Región", value=guild.region if hasattr(guild, 'region') else "No especificada", inline=True)
    embed.add_field(name="📊 Boost Level", value=f"Nivel {guild.premium_tier} ({guild.premium_subscription_count} boosts)", inline=True)
    
    # Canales principales
    canales_info = f"**Canales de Texto:** {len([c for c in guild.channels if isinstance(c, discord.TextChannel)])}\n"
    canales_info += f"**Canales de Voz:** {len([c for c in guild.channels if isinstance(c, discord.VoiceChannel)])}"
    embed.add_field(name="📍 Tipos de Canales", value=canales_info, inline=False)
    
    await ctx.send(embed=embed)

@bot.tree.command(name="serverinfo", description="Ver información del servidor")
async def slash_serverinfo(interaction: discord.Interaction):
    guild = interaction.guild
    
    embed = discord.Embed(title=f"🏛️ Información de {guild.name}", color=discord.Color.blue())
    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
    
    # Información básica
    embed.add_field(name="🆔 ID del Servidor", value=str(guild.id), inline=True)
    embed.add_field(name="👑 Owner", value=guild.owner.mention if guild.owner else "Desconocido", inline=True)
    embed.add_field(name="📅 Creado", value=guild.created_at.strftime("%d/%m/%Y %H:%M"), inline=True)
    
    # Estadísticas
    embed.add_field(name="👥 Miembros", value=f"{guild.member_count} total", inline=True)
    embed.add_field(name="📝 Canales", value=f"{len(guild.channels)} canales", inline=True)
    embed.add_field(name="🎭 Roles", value=f"{len(guild.roles)} roles", inline=True)
    
    # Más detalles
    embed.add_field(name="⚡ Nivel de Verificación", value=str(guild.verification_level).title(), inline=True)
    embed.add_field(name="🎨 Región", value=guild.region if hasattr(guild, 'region') else "No especificada", inline=True)
    embed.add_field(name="📊 Boost Level", value=f"Nivel {guild.premium_tier} ({guild.premium_subscription_count} boosts)", inline=True)
    
    # Canales principales
    canales_info = f"**Canales de Texto:** {len([c for c in guild.channels if isinstance(c, discord.TextChannel)])}\n"
    canales_info += f"**Canales de Voz:** {len([c for c in guild.channels if isinstance(c, discord.VoiceChannel)])}"
    embed.add_field(name="📍 Tipos de Canales", value=canales_info, inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.command()
async def botinfo(ctx):
    """Ver información del bot"""
    embed = discord.Embed(title="🤖 Información del Bot", color=discord.Color.purple())
    embed.set_thumbnail(url=bot.user.display_avatar.url if bot.user else None)
    
    # Información del bot
    embed.add_field(name="👤 Nombre", value=bot.user.mention if bot.user else "Desconocido", inline=True)
    embed.add_field(name="🆔 ID", value=str(bot.user.id) if bot.user else "Desconocido", inline=True)
    embed.add_field(name="👨‍💻 Creador", value="Gaming Bot", inline=True)
    
    # Estadísticas
    embed.add_field(name="📅 Inicio", value=startup_time.strftime("%d/%m/%Y %H:%M:%S"), inline=True)
    
    # Calcular uptime
    delta = discord.utils.utcnow() - startup_time
    horas = delta.seconds // 3600
    minutos = (delta.seconds % 3600) // 60
    dias = delta.days
    uptime_str = f"{dias}d {horas}h {minutos}m"
    embed.add_field(name="⏱️ Uptime", value=uptime_str, inline=True)
    
    embed.add_field(name="📚 Librerías", value="discord.py 2.0+", inline=True)
    
    # Servidores y usuarios
    embed.add_field(name="🏛️ Servidores", value=f"{len(bot.guilds)} servidores", inline=True)
    embed.add_field(name="👥 Usuarios Totales", value=f"{sum(g.member_count for g in bot.guilds)} usuarios", inline=True)
    embed.add_field(name="📌 Comandos", value="20+ comandos", inline=True)
    
    # Características
    features = "✅ Moderación automática\n✅ Sistema de verificación\n✅ Logs en tiempo real\n✅ Estadísticas de usuarios"
    embed.add_field(name="🎯 Características", value=features, inline=False)
    
    embed.set_footer(text=f"Latencia: {round(bot.latency * 1000)}ms")
    await ctx.send(embed=embed)

@bot.tree.command(name="botinfo", description="Ver información del bot")
async def slash_botinfo(interaction: discord.Interaction):
    embed = discord.Embed(title="🤖 Información del Bot", color=discord.Color.purple())
    embed.set_thumbnail(url=bot.user.display_avatar.url if bot.user else None)
    
    # Información del bot
    embed.add_field(name="👤 Nombre", value=bot.user.mention if bot.user else "Desconocido", inline=True)
    embed.add_field(name="🆔 ID", value=str(bot.user.id) if bot.user else "Desconocido", inline=True)
    embed.add_field(name="👨‍💻 Creador", value="Gaming Bot", inline=True)
    
    # Estadísticas
    embed.add_field(name="📅 Inicio", value=startup_time.strftime("%d/%m/%Y %H:%M:%S"), inline=True)
    
    # Calcular uptime
    delta = discord.utils.utcnow() - startup_time
    horas = delta.seconds // 3600
    minutos = (delta.seconds % 3600) // 60
    dias = delta.days
    uptime_str = f"{dias}d {horas}h {minutos}m"
    embed.add_field(name="⏱️ Uptime", value=uptime_str, inline=True)
    
    embed.add_field(name="📚 Librerías", value="discord.py 2.0+", inline=True)
    
    # Servidores y usuarios
    embed.add_field(name="🏛️ Servidores", value=f"{len(bot.guilds)} servidores", inline=True)
    embed.add_field(name="👥 Usuarios Totales", value=f"{sum(g.member_count for g in bot.guilds)} usuarios", inline=True)
    embed.add_field(name="📌 Comandos", value="20+ slash commands", inline=True)
    
    # Características
    features = "✅ Moderación automática\n✅ Sistema de verificación\n✅ Logs en tiempo real\n✅ Estadísticas de usuarios"
    embed.add_field(name="🎯 Características", value=features, inline=False)
    
    embed.set_footer(text=f"Latencia: {round(bot.latency * 1000)}ms")
    await interaction.response.send_message(embed=embed, ephemeral=True)
    @bot.command()
async def publicarcuenta(ctx):
    # ======== PROTECCIÓN SOLO OWNER ========
    if bot.owner_id and ctx.author.id != bot.owner_id:
        await ctx.reply("❌ Este comando solo puede usarlo el dueño del bot.", mention_author=False)
        return
    # ========================================

    embed = discord.Embed(
        title="🎅🎄✨ Cuenta Steam Navideña ✨🎄🎅",
        description=(
            "🎁 **Servidor de ventas:**\n"
            "🔗 S4GM Store: https://discord.gg/2aJ2vhbMTC\n\n"
            "──────────────────────────────\n"
            "🎄 **Usuario:**\n`moguchichlen228`\n"
            "✨ **Contraseña:**\n`JBVAo_432fe`\n"
            "──────────────────────────────\n"
            "🎮 **Regalos dentro del trineo:**\n"
            "• The Walking Dead The Telltale Definitive Series\n\n"
            "🎄✨ Si se aparece el **duende Error 50**, abre el regalo en el **minuto 3:30 del video** para disipar la maldición ❄️🔥"
        ),
        color=discord.Color.from_rgb(200, 50, 50)
    )

    embed.set_image(url="https://i.imgur.com/IfT3a0Y.jpeg")

    view = discord.ui.View()
    boton = discord.ui.Button(
        label="🎁 Solución Error 50",
        url="https://youtu.be/dQw4w9WgXcQ"
    )
    view.add_item(boton)

    await ctx.send(embed=embed, view=view)

# ----- INICIAR BOT -----
TOKEN = os.getenv('DISCORD_TOKEN')
if TOKEN is None:
    print("ERROR: No se encontró el token de Discord.")
    print("Por favor, configura la variable de entorno DISCORD_TOKEN en los Secrets de Replit.")
else:
    bot.run(TOKEN)
