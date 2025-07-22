import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import os

if os.getenv("RENDER") is None:
    from dotenv import load_dotenv
    load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class RoleButtonView(discord.ui.View):
    def __init__(self, role: discord.Role, duration: int, notify_channel: discord.TextChannel | None):
        super().__init__(timeout=None)
        self.role = role
        self.duration = duration
        self.notify_channel = notify_channel


    @discord.ui.button(label="ロールを受け取る", style=discord.ButtonStyle.primary)
    async def grant_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        role = self.role

        if role in member.roles:
            await interaction.response.send_message("すでにロールを持っています。", ephemeral=True)
            return

        await member.add_roles(role)
        await interaction.response.send_message(
            f"{role.name} を付与しました！\n{self.duration}分後に自動で外れます。",
            ephemeral=True
        )

        await asyncio.sleep(self.duration * 60)
        await member.remove_roles(role)

        if self.notify_channel:
            try:
                await self.notify_channel.send(
                    f"{member.mention} の {self.role.name} ロールを自動で剥奪しました。"
                )
            except:
                pass  # 通知チャンネルに送れなかった場合も無視



class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):
        await self.tree.sync()
        print("スラッシュコマンドを同期しました")


bot = MyBot()


@bot.event
async def on_ready():
    print(f"Bot is online: {bot.user}")


# 📌 スラッシュコマンド：/setup_button
@bot.tree.command(name="setup_button", description="ロール付与ボタンを作成します")
@app_commands.describe(
    role="付与したいロール",
    minutes="ロールを保持する時間（分）",
    notify_channel="ロール剥奪時に通知するチャンネル"
)
async def setup_button(interaction: discord.Interaction, role: discord.Role, minutes: int = 10, notify_channel: discord.TextChannel = None):

    if minutes <= 0:
        await interaction.response.send_message("時間は1分以上にしてください。", ephemeral=True)
        return

    view = RoleButtonView(role, duration=minutes, notify_channel=notify_channel)
    await interaction.response.send_message(
        f"{role.name} を取得できるボタンを送信します。",
        ephemeral=True
    )
    await interaction.channel.send(f"{role.name} を取得したい人は以下を押してください：", view=view)


# 📌 スラッシュコマンド：/help
@bot.tree.command(name="help", description="このBotの使い方を表示します")
async def help_command(interaction: discord.Interaction):
    help_text = (
        "**📘 Botの使い方**\n\n"
        "`/setup_button ロール 時間(分) 通知チャンネル` を実行すると、ロール取得用のボタン付きメッセージが投稿されます。\n"
        "ボタンを押したユーザーにはそのロールが一時的に付与され、指定時間後に自動で削除されます。\n\n"
        "**🔔 通知チャンネルについて：**\n"
        "- 通知チャンネルを指定すると、ロールの剥奪時にそのチャンネルへメンション付きで通知されます。\n"
        "- 通知チャンネルは、必要に応じて通知設定を「メンション時のみ」にしてください（BotはDMを送りません）。\n"
        "- 通知チャンネルの指定は任意です（省略可）。\n\n"
        "**📝 使用例：**\n"
        "`/setup_button @一時入室 10 #ロール通知`\n"
        "→ 「一時入室」ロールを10分間付与し、10分後に #ロール通知 にメンション付きで剥奪通知を投稿します。\n\n"
        "**⚠️ 注意：**\n"
        "- Botのロールは、付与・剥奪対象のロールより上位にある必要があります。\n"
        "- ロールやチャンネルは選択式（オートコンプリート）で指定できます。\n"
    )
    await interaction.response.send_message(help_text, ephemeral=True)


bot.run(TOKEN)
