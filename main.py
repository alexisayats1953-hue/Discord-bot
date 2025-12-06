import discord
from discord.ext import commands
import os
import asyncio
import random
import string
from datetime import datetime
from collections import defaultdict

# -------------------------
# CONFIGURACIÓN DEL BOT
# -------------------------
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="?", intents=intents)

# Variables internas
advertencias = defaultdict(int)
toxicidad_puntos = defaultdict(int)
mensajes_enviados = defaultdict(int)
mute_historial = defaultdict(list)
eventos_tiempo_real = []
logs_channel_id = {}
codigos_verificacion = {}

startup_time = datetime.utcnow()

# -------------------------
# FUNCIONES
# -------------------------

def add_evento(tipo, descripcion, detalles=""):
    eventos_tiempo_real.append({
        "tipo": tipo,
        "descripcion": descripcion,
        "detalles": detalles,
        "timestamp": datetime.utcnow().strftime("%d/%m/%Y %H:%M:%S")
    })

async def enviar_log(guild, texto):
    canal_id = logs_channel_id.get(guild.id)
    if canal_id:
        canal = guild.get_channel(canal_id)
        if canal:
            await canal.send(texto)

# -------------------------
# EVENTO: BOT LISTO
# -------------------------

@bot.event
async def on_ready():
    print(f"Bot iniciado como {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Slash commands sincronizados: {len(synced)}")
    except Exception as e:
        print(f"Error sincronizando slash commands: {e}")

# -------------------------
# SISTEMA DE VERIFICACIÓN
# -------------------------

class VerificacionModal(discord.ui.Modal, title="Ingresar Código de Verificación"):
    codigo = discord.ui.TextInput(label="Código", placeholder="Ingresa tu código aquí")

    async def on_submit(self, interaction: discord.Interaction):
        usuario = interaction.user
        guild = interaction.guild

        if usuario.id not in codigos_verificacion:
            return await interaction.response.send_message("❌ No tienes un código activo.", ephemeral=True)

        if self.codigo.value != codigos_verificacion[usuario.id]:
            return await interaction.response.send_message("❌ Código incorrecto.", ephemeral=True)

        rol = guild.get_role(1431669432387899583)
        await usuario.add_roles(rol)

        codigos_verificacion.pop(usuario.id, None)

        embed = discord.Embed(
            title="🎉 ¡Verificado!",
            description=f"Bienvenido {usuario.mention}",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class VerificacionView(discord.ui.View):
    @discord.ui.button(label="Verificarse", style=discord.ButtonStyle.green)
    async def verify(self, interaction, button):
        usuario = interaction.user
        guild = interaction.guild

        if usuario.id in codigos_verificacion:
            return await interaction.response.send_message("Ya tienes un código pendiente.", ephemeral=True)

        codigo = ''.join(random.choices(string.digits, k=6))
        codigos_verificacion[usuario.id] = codigo

        try:
            await usuario.send(f"Tu código de verificación es: **{codigo}**")
        except:
            return await interaction.response.send_message("Activa tus mensajes privados.", ephemeral=True)

        await interaction.response.send_message("Código enviado por DM.", ephemeral=True)

# Comando para enviar la verificación
@bot.command()
async def verify(ctx):
    embed = discord.Embed(
        title="Verificación",
        description="Pulsa el botón para verificarte.",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed, view=VerificacionView())

# -------------------------
# COMANDO HELP
# -------------------------

@bot.command()
async def help(ctx):
    embed = discord.Embed(title="📚 Ayuda del Bot", color=discord.Color.blurple())
    embed.add_field(name="verify", value="Inicia verificación", inline=False)
    embed.add_field(name="serverinfo", value="Información del servidor", inline=False)
    embed.add_field(name="botinfo", value="Información del bot", inline=False)
    await ctx.send(embed=embed)

# -------------------------
# INFO DEL SERVIDOR
# -------------------------

@bot.command()
async def serverinfo(ctx):
    guild = ctx.guild
    embed = discord.Embed(title=f"Información de {guild.name}", color=discord.Color.blue())
    embed.add_field(name="Miembros", value=guild.member_count)
    embed.add_field(name="Roles", value=len(guild.roles))
    embed.add_field(name="Canales", value=len(guild.channels))
    await ctx.send(embed=embed)

# -------------------------
# BOT INFO
# -------------------------

@bot.command()
async def botinfo(ctx):
    embed = discord.Embed(title="🤖 Información del Bot", color=discord.Color.magenta())
    embed.add_field(name="Creado", value=startup_time.strftime("%d/%m/%Y %H:%M:%S"))
    embed.add_field(name="Latencia", value=f"{round(bot.latency*1000)}ms")
    await ctx.send(embed=embed)

# -------------------------
# INICIO DEL BOT
# -------------------------

TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN is None:
    print("❌ No se encontró DISCORD_TOKEN en Render.")
else:
    bot.run(TOKEN)
