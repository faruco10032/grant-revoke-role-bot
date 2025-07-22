# -*- coding: utf-8 -*-
"""
Python 3.8 でも動くように
  • PEP 604 の `|` を Optional[...] に置き換え
  • typing.Optional をインポート
そのほかのロジックは変更なし
"""
import os
import asyncio
from typing import Optional        # ★ 追加

import discord
from discord.ext import commands
from discord import app_commands

# ──────────────────────────────────────────────────────────────
# 環境変数読み込み
# ──────────────────────────────────────────────────────────────
if os.getenv("RENDER") is None:    # NAS などローカル実行時
    from dotenv import load_dotenv
    load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set in environment variables.")

# ──────────────────────────────────────────────────────────────
# Bot Intents
# ──────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# ──────────────────────────────────────────────────────────────
# ボタン用 View
# ──────────────────────────────────────────────────────────────
class RoleButtonView(discord.ui.View):
    def __init__(
        self,
        role: discord.Role,
        duration: int,
        notify_channel: Optional[discord.TextChannel] = None   # ★ Optional に変更
    ) -> None:
        super().__init__(timeout=None)
        self.role = role
        self.duration = duration
        self.notify_channel = notify_channel

    @discord.ui.button(label="ロールを受け取る", style=discord.ButtonStyle.primary)
    async def grant_role(                      # noqa: D401
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        member = interaction.user
        role = self.role

        if role in member.roles:
            await interaction.response.send_message(
                "すでにロールを持っています。",
                ephemeral=True
            )
            return

        await member.add_roles(role)
        await interaction.response.send_message(
            f"{role.name} を付与しました！\n{self.duration}分後に自動で外れます。",
            ephemeral=True
        )

        # 指定分だけ待ってからロールを剥奪
        await asyncio.sleep(self.duration * 60)
        await member.remove_roles(role)

        # 通知チャンネルがあれば送信（失敗は握りつぶす）
        if self.notify_channel:
            try:
                await self.notify_channel.send(
                    f"{member.mention} の {role.name} ロールを自動で剥奪しました。"
                )
            except Exception:
                pass

# ──────────────────────────────────────────────────────────────
# Bot 本体
# ──────────────────────────────────────────────────────────────
class MyBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )

    async def setup_hook(self) -> None:
        await self.tree.sync()
        print("スラッシュコマンドを同期しました")

bot = MyBot()

@bot.event
async def on_ready() -> None:
    print(f"Bot is online: {bot.user}")

# ──────────────────────────────────────────────────────────────
# /setup_button コマンド
# ──────────────────────────────────────────────────────────────
@bot.tree.command(name="setup_button", description="ロール付与ボタンを作成します")
@app_commands.describe(
    role="付与したいロール",
    minutes="ロールを保持する時間（分）",
    notify_channel="ロール剥奪時に通知するチャンネル"
)
async def setup_button(
    interaction: discord.Interaction,
    role: discord.Role,
    minutes: int = 10,
    notify_channel: Optional[discord.TextChannel] = None       # ★ Optional に変更
):
    if minutes <= 0:
        await interaction.response.send_message(
            "時間は1分以上にしてください。",
            ephemeral=True
        )
        return

    view = RoleButtonView(role, duration=minutes, notify_channel=notify_channel)

    # 自分にだけ「送信したよ」と返す
    await interaction.response.send_message(
        f"{role.name} を取得できるボタンを送信します。",
        ephemeral=True
    )
    # 公開チャンネルにボタン付きメッセージを投稿
    await interaction.channel.send(
        f"{role.name} を取得したい人は以下を押してください：",
        view=view
    )

# ──────────────────────────────────────────────────────────────
# /help コマンド
# ──────────────────────────────────────────────────────────────
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

# ──────────────────────────────────────────────────────────────
# 起動
# ──────────────────────────────────────────────────────────────
bot.run(TOKEN)
