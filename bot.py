# -*- coding: utf-8 -*-
"""
Discord Bot: 一時ロール付与・自動剥奪
  - JSON ファイルでタイマーを永続化（Bot 再起動でも剥奪漏れなし）
  - custom_id 付き永続 View（Bot 再起動後もボタンが動作）
  - バックグラウンドタスクで期限切れロールを定期チェック
  - Python 3.8+ 対応
"""
import json
import os
import time
from pathlib import Path
from typing import Optional, List, Dict

import discord
from discord.ext import commands, tasks
from discord import app_commands

# ──────────────────────────────────────────────────────────────
# 環境変数読み込み
# ──────────────────────────────────────────────────────────────
if os.getenv("RENDER") is None:
    from dotenv import load_dotenv
    load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set in environment variables.")

# ──────────────────────────────────────────────────────────────
# 定数
# ──────────────────────────────────────────────────────────────
TIMERS_FILE = Path(__file__).parent / "role_timers.json"

# ──────────────────────────────────────────────────────────────
# タイマー永続化ヘルパー
# ──────────────────────────────────────────────────────────────
def load_timers():
    # type: () -> List[Dict]
    if not TIMERS_FILE.exists():
        return []
    try:
        with open(TIMERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def save_timers(timers):
    # type: (List[Dict]) -> None
    with open(TIMERS_FILE, "w", encoding="utf-8") as f:
        json.dump(timers, f, ensure_ascii=False, indent=2)


def add_timer(guild_id, user_id, role_id, expire_at, notify_channel_id=None):
    # type: (int, int, int, float, Optional[int]) -> None
    timers = load_timers()
    # 重複防止（同じユーザー・ロールの組は上書き）
    timers = [
        t for t in timers
        if not (t["guild_id"] == guild_id
                and t["user_id"] == user_id
                and t["role_id"] == role_id)
    ]
    timers.append({
        "guild_id": guild_id,
        "user_id": user_id,
        "role_id": role_id,
        "expire_at": expire_at,
        "notify_channel_id": notify_channel_id,
    })
    save_timers(timers)


def remove_timer(guild_id, user_id, role_id):
    # type: (int, int, int) -> None
    timers = load_timers()
    timers = [
        t for t in timers
        if not (t["guild_id"] == guild_id
                and t["user_id"] == user_id
                and t["role_id"] == role_id)
    ]
    save_timers(timers)


# ──────────────────────────────────────────────────────────────
# Bot Intents
# ──────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# ──────────────────────────────────────────────────────────────
# 永続ボタン用 View
# ──────────────────────────────────────────────────────────────
class RoleButtonView(discord.ui.View):
    """custom_id 形式: role_grant:<role_id>:<duration_minutes>[:<notify_channel_id>]"""

    def __init__(
        self,
        role_id: int,
        duration: int,
        notify_channel_id: Optional[int] = None,
    ) -> None:
        super().__init__(timeout=None)
        self.role_id = role_id
        self.duration = duration
        self.notify_channel_id = notify_channel_id

        # custom_id を動的に組み立て
        parts = ["role_grant", str(role_id), str(duration)]
        if notify_channel_id is not None:
            parts.append(str(notify_channel_id))
        custom_id = ":".join(parts)

        # ボタンを手動追加（custom_id を動的に設定するため）
        button = discord.ui.Button(
            label="ロールを受け取る",
            style=discord.ButtonStyle.primary,
            custom_id=custom_id,
        )
        button.callback = self.grant_role
        self.add_item(button)

    async def grant_role(self, interaction: discord.Interaction):
        member = interaction.user
        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message(
                "サーバー内でのみ使用できます。", ephemeral=True
            )
            return

        role = guild.get_role(self.role_id)
        if role is None:
            await interaction.response.send_message(
                "対象のロールが見つかりません。削除された可能性があります。",
                ephemeral=True,
            )
            return

        if role in member.roles:
            await interaction.response.send_message(
                "すでにロールを持っています。", ephemeral=True
            )
            return

        try:
            await member.add_roles(role)
        except discord.Forbidden:
            await interaction.response.send_message(
                "Botの権限が不足しているためロールを付与できません。\n"
                "Botのロールが付与対象のロールより上位にあるか確認してください。",
                ephemeral=True,
            )
            return
        except discord.HTTPException as e:
            await interaction.response.send_message(
                "ロール付与中にエラーが発生しました: {}".format(e),
                ephemeral=True,
            )
            return

        expire_at = time.time() + self.duration * 60
        add_timer(
            guild_id=guild.id,
            user_id=member.id,
            role_id=role.id,
            expire_at=expire_at,
            notify_channel_id=self.notify_channel_id,
        )

        await interaction.response.send_message(
            "{} を付与しました！\n{}分後に自動で外れます。".format(
                role.name, self.duration
            ),
            ephemeral=True,
        )


# ──────────────────────────────────────────────────────────────
# custom_id からViewを復元するユーティリティ
# ──────────────────────────────────────────────────────────────
def parse_custom_id(custom_id):
    # type: (str) -> Optional[Dict]
    """custom_id を解析して辞書を返す。不正な形式なら None。"""
    parts = custom_id.split(":")
    if len(parts) < 3 or parts[0] != "role_grant":
        return None
    try:
        result = {
            "role_id": int(parts[1]),
            "duration": int(parts[2]),
            "notify_channel_id": int(parts[3]) if len(parts) >= 4 else None,
        }
        return result
    except (ValueError, IndexError):
        return None


# ──────────────────────────────────────────────────────────────
# Bot 本体
# ──────────────────────────────────────────────────────────────
class MyBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
        )

    async def setup_hook(self) -> None:
        # 既存ボタンを復元するため、汎用の永続 View を登録
        self.add_view(PersistentRoleView())

        await self.tree.sync()
        print("スラッシュコマンドを同期しました")

        # バックグラウンドタスク開始
        check_expired_roles.start()


class PersistentRoleView(discord.ui.View):
    """Bot 再起動後に既存ボタンを拾うための汎用 View。
    custom_id が role_grant: で始まるボタンを全てハンドルする。"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="ロールを受け取る",
        style=discord.ButtonStyle.primary,
        custom_id="role_grant_persistent",
    )
    async def _placeholder(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass  # 実際には interaction_check で処理

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        custom_id = interaction.data.get("custom_id", "") if interaction.data else ""
        parsed = parse_custom_id(custom_id)
        if parsed is None:
            return False

        # 動的にViewを構築して処理を委譲
        view = RoleButtonView(
            role_id=parsed["role_id"],
            duration=parsed["duration"],
            notify_channel_id=parsed["notify_channel_id"],
        )
        await view.grant_role(interaction)
        return False  # 既に応答済みなので False


bot = MyBot()


@bot.event
async def on_ready() -> None:
    print("Bot is online: {}".format(bot.user))


@bot.event
async def on_interaction(interaction: discord.Interaction):
    """custom_id ベースの永続ボタンをハンドルする。"""
    if interaction.type != discord.InteractionType.component:
        return
    custom_id = interaction.data.get("custom_id", "") if interaction.data else ""
    parsed = parse_custom_id(custom_id)
    if parsed is None:
        return

    view = RoleButtonView(
        role_id=parsed["role_id"],
        duration=parsed["duration"],
        notify_channel_id=parsed["notify_channel_id"],
    )
    await view.grant_role(interaction)


# ──────────────────────────────────────────────────────────────
# バックグラウンドタスク: 期限切れロールを定期チェック
# ──────────────────────────────────────────────────────────────
@tasks.loop(seconds=30)
async def check_expired_roles():
    now = time.time()
    timers = load_timers()
    remaining = []

    for t in timers:
        if t["expire_at"] > now:
            remaining.append(t)
            continue

        # 期限切れ → ロール剥奪
        guild = bot.get_guild(t["guild_id"])
        if guild is None:
            continue

        member = guild.get_member(t["user_id"])
        role = guild.get_role(t["role_id"])

        if member is None or role is None:
            # メンバーやロールが見つからない場合はスキップ（タイマーは削除）
            continue

        if role not in member.roles:
            # 既に外れている場合はスキップ
            continue

        try:
            await member.remove_roles(role)
            print("ロール剥奪: {} から {} を剥奪".format(member, role.name))
        except discord.Forbidden:
            print("権限不足: {} から {} を剥奪できません".format(member, role.name))
            remaining.append(t)  # リトライのため残す
            continue
        except discord.HTTPException as e:
            print("ロール剥奪エラー: {}".format(e))
            remaining.append(t)
            continue

        # 通知チャンネルがあれば送信
        if t.get("notify_channel_id"):
            ch = guild.get_channel(t["notify_channel_id"])
            if ch is not None:
                try:
                    await ch.send(
                        "{} の {} ロールを自動で剥奪しました。".format(
                            member.mention, role.name
                        )
                    )
                except Exception:
                    pass

    save_timers(remaining)


@check_expired_roles.before_loop
async def before_check():
    await bot.wait_until_ready()


# ──────────────────────────────────────────────────────────────
# /setup_button コマンド（管理者のみ）
# ──────────────────────────────────────────────────────────────
@bot.tree.command(name="setup_button", description="ロール付与ボタンを作成します")
@app_commands.describe(
    role="付与したいロール",
    minutes="ロールを保持する時間（分）",
    notify_channel="ロール剥奪時に通知するチャンネル",
)
@app_commands.default_permissions(administrator=True)
async def setup_button(
    interaction: discord.Interaction,
    role: discord.Role,
    minutes: int = 10,
    notify_channel: Optional[discord.TextChannel] = None,
):
    if minutes <= 0:
        await interaction.response.send_message(
            "時間は1分以上にしてください。", ephemeral=True
        )
        return

    notify_id = notify_channel.id if notify_channel else None
    view = RoleButtonView(
        role_id=role.id, duration=minutes, notify_channel_id=notify_id
    )

    await interaction.response.send_message(
        "{} を取得できるボタンを送信します。".format(role.name),
        ephemeral=True,
    )
    await interaction.channel.send(
        "{} を取得したい人は以下を押してください：".format(role.name),
        view=view,
    )


# ──────────────────────────────────────────────────────────────
# /help コマンド
# ──────────────────────────────────────────────────────────────
@bot.tree.command(name="help", description="このBotの使い方を表示します")
async def help_command(interaction: discord.Interaction):
    help_text = (
        "**Botの使い方**\n\n"
        "`/setup_button ロール 時間(分) 通知チャンネル` を実行すると、"
        "ロール取得用のボタン付きメッセージが投稿されます。\n"
        "ボタンを押したユーザーにはそのロールが一時的に付与され、"
        "指定時間後に自動で削除されます。\n\n"
        "**通知チャンネルについて：**\n"
        "- 通知チャンネルを指定すると、ロールの剥奪時にそのチャンネルへ"
        "メンション付きで通知されます。\n"
        "- 通知チャンネルの指定は任意です（省略可）。\n\n"
        "**使用例：**\n"
        "`/setup_button @一時入室 10 #ロール通知`\n"
        "→ 「一時入室」ロールを10分間付与し、10分後に #ロール通知 に"
        "剥奪通知を投稿します。\n\n"
        "**注意：**\n"
        "- Botのロールは、付与・剥奪対象のロールより上位にある必要があります。\n"
        "- このコマンドは管理者のみ使用できます。\n"
    )
    await interaction.response.send_message(help_text, ephemeral=True)


# ──────────────────────────────────────────────────────────────
# 起動
# ──────────────────────────────────────────────────────────────
bot.run(TOKEN)
