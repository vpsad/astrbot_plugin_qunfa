import asyncio
import json
import os
import random
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_type import MessageType  # 导入 MessageType
from astrbot.api.star import Context, Star, register
import astrbot.api.message_components as Comp

@register("group_sender", "Trae AI", "群发消息插件，支持定时发送随机内容到多个群", "1.0.0", "https://github.com/traeai/astrbot-plugins")
class GroupSenderPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.config_path = os.path.join(context.get_plugin_data_dir(), "config.json")
        self.records_path = os.path.join(context.get_plugin_data_dir(), "records.json")
        self.config = self.load_config()
        self.records = self.load_records()
        self.scheduled_task = None
        # 启动时检查是否需要启动定时任务
        asyncio.create_task(self.init_scheduler())
    
    def load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        default_config = {
            "random_contents": ["这是默认的随机内容1", "这是默认的随机内容2"],
            "interval_seconds": 5,
            "target_groups": [],
            "schedule": {
                "enabled": False,
                "type": "daily",  # daily 或 interval
                "time": "08:00",  # 每天的发送时间 (HH:MM)
                "interval_days": 1  # 间隔天数
            }
        }
        
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                self.logger.error(f"加载配置文件失败: {e}")
                return default_config
        else:
            # 确保目录存在
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            # 保存默认配置
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(default_config, f, ensure_ascii=False, indent=4)
            return default_config
    
    def save_config(self) -> None:
        """保存配置到文件"""
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=4)
    
    def load_records(self) -> List[Dict[str, Any]]:
        """加载发送记录"""
        if os.path.exists(self.records_path):
            try:
                with open(self.records_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                self.logger.error(f"加载记录文件失败: {e}")
                return []
        return []
    
    def save_records(self) -> None:
        """保存发送记录到文件"""
        with open(self.records_path, "w", encoding="utf-8") as f:
            json.dump(self.records, f, ensure_ascii=False, indent=4)
    
    def add_record(self, group_id: str, content: str, status: str) -> None:
        """添加发送记录"""
        record = {
            "timestamp": int(time.time()),
            "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "group_id": group_id,
            "content": content,
            "status": status
        }
        self.records.append(record)
        # 限制记录数量，最多保留1000条
        if len(self.records) > 1000:
            self.records = self.records[-1000:]
        self.save_records()
    
    async def init_scheduler(self) -> None:
        """初始化定时任务"""
        if self.config["schedule"]["enabled"]:
            await self.schedule_next_run()
    
    async def schedule_next_run(self) -> None:
        """安排下一次定时发送"""
        if not self.config["schedule"]["enabled"]:
            return
        
        now = datetime.now()
        
        if self.config["schedule"]["type"] == "daily":
            # 每天固定时间发送
            hour, minute = map(int, self.config["schedule"]["time"].split(":"))
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            # 如果今天的时间已经过了，安排到明天
            if next_run <= now:
                next_run += timedelta(days=1)
        else:
            # 按间隔天数发送
            interval_days = self.config["schedule"]["interval_days"]
            hour, minute = map(int, self.config["schedule"]["time"].split(":"))
            
            # 查找最近一次发送记录
            last_scheduled_send = None
            for record in reversed(self.records):
                if record.get("scheduled", False):
                    try:
                        last_scheduled_send = datetime.strptime(record["datetime"], "%Y-%m-%d %H:%M:%S")
                        break
                    except:
                        pass
            
            if last_scheduled_send:
                next_run = last_scheduled_send + timedelta(days=interval_days)
                next_run = next_run.replace(hour=hour, minute=minute, second=0, microsecond=0)
                
                # 如果计算出的下次发送时间已经过了，从今天开始重新计算
                if next_run <= now:
                    next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    if next_run <= now:
                        next_run += timedelta(days=1)
            else:
                # 没有发送记录，从今天开始
                next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if next_run <= now:
                    next_run += timedelta(days=1)
        
        # 计算等待时间
        wait_seconds = (next_run - now).total_seconds()
        
        # 取消之前的任务（如果有）
        if self.scheduled_task and not self.scheduled_task.done():
            self.scheduled_task.cancel()
        
        # 创建新的定时任务
        self.scheduled_task = asyncio.create_task(self.run_scheduled_task(wait_seconds))
        
        self.logger.info(f"下一次定时群发将在 {next_run.strftime('%Y-%m-%d %H:%M:%S')} 执行，等待 {wait_seconds:.2f} 秒")
    
    async def run_scheduled_task(self, wait_seconds: float) -> None:
        """运行定时任务"""
        try:
            await asyncio.sleep(wait_seconds)
            await self.send_to_all_groups(scheduled=True)
            # 安排下一次运行
            await self.schedule_next_run()
        except asyncio.CancelledError:
            self.logger.info("定时任务被取消")
        except Exception as e:
            self.logger.error(f"定时任务执行出错: {e}")
            # 出错后也要尝试安排下一次运行
            await self.schedule_next_run()
    
    async def send_to_all_groups(self, scheduled: bool = False) -> List[Dict[str, Any]]:
        """向所有配置的群发送随机内容"""
        results = []
        
        if not self.config["target_groups"]:
            return [{"error": "没有配置目标群"}]
        
        if not self.config["random_contents"]:
            return [{"error": "没有配置随机内容"}]
        
        for group_id in self.config["target_groups"]:
            try:
                # 随机选择一条内容
                content = random.choice(self.config["random_contents"])
                
                # 发送消息
                await self.context.send_group_msg(group_id=group_id, message=[Comp.Plain(text=content)])
                
                # 记录发送
                self.add_record(group_id, content, "success")
                if scheduled:
                    # 标记为定时发送的记录
                    self.records[-1]["scheduled"] = True
                    self.save_records()
                
                results.append({
                    "group_id": group_id,
                    "content": content,
                    "status": "success"
                })
                
                # 等待指定的间隔时间
                if group_id != self.config["target_groups"][-1]:  # 如果不是最后一个群
                    await asyncio.sleep(self.config["interval_seconds"])
            
            except Exception as e:
                error_msg = str(e)
                self.logger.error(f"向群 {group_id} 发送消息失败: {error_msg}")
                self.add_record(group_id, "发送失败", f"error: {error_msg}")
                
                results.append({
                    "group_id": group_id,
                    "error": error_msg,
                    "status": "failed"
                })
        
        return results
    
    # 指令：立即群发
    @filter.command("groupsend")
    async def cmd_group_send(self, event: AstrMessageEvent):
        '''立即向所有配置的群发送随机内容'''
        # 检查权限（只允许管理员使用）
        if not await self.context.check_permission(event, "admin"):
            yield event.plain_result("权限不足，只有管理员可以使用此命令")
            return
        
        yield event.plain_result("开始群发消息...")
        
        results = await self.send_to_all_groups()
        
        # 生成报告
        success_count = sum(1 for r in results if r.get("status") == "success")
        fail_count = len(results) - success_count
        
        report = f"群发完成，成功: {success_count}，失败: {fail_count}\n"
        if fail_count > 0:
            report += "失败详情:\n"
            for r in results:
                if r.get("status") != "success":
                    report += f"- 群 {r.get('group_id')}: {r.get('error')}\n"
        
        yield event.plain_result(report)
    
    # 指令组：配置管理
    @filter.command_group("groupsender")
    def cmd_group_sender(self):
        '''群发插件配置管理'''
        pass
    
    # 查看当前配置
    @cmd_group_sender.command("config")
    async def cmd_show_config(self, event: AstrMessageEvent):
        '''查看当前配置'''
        if not await self.context.check_permission(event, "admin"):
            yield event.plain_result("权限不足，只有管理员可以使用此命令")
            return
        
        # 格式化配置信息
        config_str = "当前配置:\n"
        config_str += f"- 目标群数量: {len(self.config['target_groups'])}\n"
        config_str += f"- 随机内容数量: {len(self.config['random_contents'])}\n"
        config_str += f"- 发送间隔: {self.config['interval_seconds']}秒\n"
        config_str += "- 定时发送: "
        
        if self.config["schedule"]["enabled"]:
            if self.config["schedule"]["type"] == "daily":
                config_str += f"每天 {self.config['schedule']['time']}\n"
            else:
                config_str += f"每 {self.config['schedule']['interval_days']} 天的 {self.config['schedule']['time']}\n"
        else:
            config_str += "未启用\n"
        
        # 显示目标群列表
        if self.config["target_groups"]:
            config_str += "\n目标群列表:\n"
            for i, group_id in enumerate(self.config["target_groups"]):
                config_str += f"{i+1}. {group_id}\n"
        
        # 显示随机内容
        if self.config["random_contents"]:
            config_str += "\n随机内容列表:\n"
            for i, content in enumerate(self.config["random_contents"]):
                # 内容可能很长，只显示前20个字符
                display_content = content[:20] + "..." if len(content) > 20 else content
                config_str += f"{i+1}. {display_content}\n"
        
        yield event.plain_result(config_str)
    
    # 添加随机内容
    @cmd_group_sender.command("add_content")
    async def cmd_add_content(self, event: AstrMessageEvent, content: str):
        '''添加随机内容'''
        if not await self.context.check_permission(event, "admin"):
            yield event.plain_result("权限不足，只有管理员可以使用此命令")
            return
        
        self.config["random_contents"].append(content)
        self.save_config()
        
        yield event.plain_result(f"已添加随机内容: {content}")
    
    # 删除随机内容
    @cmd_group_sender.command("del_content")
    async def cmd_del_content(self, event: AstrMessageEvent, index: int):
        '''删除随机内容，索引从1开始'''
        if not await self.context.check_permission(event, "admin"):
            yield event.plain_result("权限不足，只有管理员可以使用此命令")
            return
        
        if index < 1 or index > len(self.config["random_contents"]):
            yield event.plain_result(f"索引超出范围，有效范围: 1-{len(self.config['random_contents'])}")
            return
        
        removed = self.config["random_contents"].pop(index - 1)
        self.save_config()
        
        yield event.plain_result(f"已删除随机内容: {removed}")
    
    # 添加目标群
    @cmd_group_sender.command("add_group")
    async def cmd_add_group(self, event: AstrMessageEvent, group_id: str):
        '''添加目标群'''
        if not await self.context.check_permission(event, "admin"):
            yield event.plain_result("权限不足，只有管理员可以使用此命令")
            return
        
        if group_id in self.config["target_groups"]:
            yield event.plain_result(f"群 {group_id} 已在目标列表中")
            return
        
        self.config["target_groups"].append(group_id)
        self.save_config()
        
        yield event.plain_result(f"已添加目标群: {group_id}")
    
    # 删除目标群
    @cmd_group_sender.command("del_group")
    async def cmd_del_group(self, event: AstrMessageEvent, group_id: str):
        '''删除目标群'''
        if not await self.context.check_permission(event, "admin"):
            yield event.plain_result("权限不足，只有管理员可以使用此命令")
            return
        
        if group_id not in self.config["target_groups"]:
            yield event.plain_result(f"群 {group_id} 不在目标列表中")
            return
        
        self.config["target_groups"].remove(group_id)
        self.save_config()
        
        yield event.plain_result(f"已删除目标群: {group_id}")
    
    # 设置发送间隔
    @cmd_group_sender.command("set_interval")
    async def cmd_set_interval(self, event: AstrMessageEvent, seconds: int):
        '''设置发送间隔（秒）'''
        if not await self.context.check_permission(event, "admin"):
            yield event.plain_result("权限不足，只有管理员可以使用此命令")
            return
        
        if seconds < 1:
            yield event.plain_result("间隔时间必须大于0秒")
            return
        
        self.config["interval_seconds"] = seconds
        self.save_config()
        
        yield event.plain_result(f"已设置发送间隔为 {seconds} 秒")
    
    # 设置定时发送
    @cmd_group_sender.command("set_schedule")
    async def cmd_set_schedule(self, event: AstrMessageEvent, enabled: str, schedule_type: str = "daily", time: str = "08:00", interval_days: int = 1):
        '''设置定时发送，参数: enabled(on/off), type(daily/interval), time(HH:MM), interval_days(天数)'''
        if not await self.context.check_permission(event, "admin"):
            yield event.plain_result("权限不足，只有管理员可以使用此命令")
            return
        
        # 检查参数
        if enabled.lower() not in ["on", "off"]:
            yield event.plain_result("enabled 参数必须是 on 或 off")
            return
        
        if schedule_type not in ["daily", "interval"]:
            yield event.plain_result("type 参数必须是 daily 或 interval")
            return
        
        # 检查时间格式
        try:
            hour, minute = map(int, time.split(":"))
            if hour < 0 or hour > 23 or minute < 0 or minute > 59:
                raise ValueError()
        except:
            yield event.plain_result("time 参数格式必须是 HH:MM")
            return
        
        if interval_days < 1:
            yield event.plain_result("interval_days 参数必须大于0")
            return
        
        # 更新配置
        self.config["schedule"]["enabled"] = (enabled.lower() == "on")
        self.config["schedule"]["type"] = schedule_type
        self.config["schedule"]["time"] = time
        self.config["schedule"]["interval_days"] = interval_days
        self.save_config()
        
        # 重新安排定时任务
        asyncio.create_task(self.schedule_next_run())
        
        if enabled.lower() == "on":
            yield event.plain_result(f"已启用定时发送: {schedule_type} 模式, 时间 {time}" + 
                                    (f", 每 {interval_days} 天" if schedule_type == "interval" else ""))
        else:
            yield event.plain_result("已禁用定时发送")
    
    # 查看发送记录
    @cmd_group_sender.command("records")
    async def cmd_show_records(self, event: AstrMessageEvent, count: int = 10):
        '''查看发送记录，参数: count(显示数量)'''
        if not await self.context.check_permission(event, "admin"):
            yield event.plain_result("权限不足，只有管理员可以使用此命令")
            return
        
        if count < 1:
            yield event.plain_result("显示数量必须大于0")
            return
        
        if not self.records:
            yield event.plain_result("暂无发送记录")
            return
        
        # 获取最近的记录
        recent_records = self.records[-count:]
        
        # 生成报告
        report = f"最近 {len(recent_records)} 条发送记录:\n"
        for i, record in enumerate(recent_records):
            status = "成功" if record.get("status") == "success" else f"失败: {record.get('status')}"
            scheduled = " (定时)" if record.get("scheduled", False) else ""
            report += f"{i+1}. [{record.get('datetime')}]{scheduled} 群 {record.get('group_id')}: {status}\n"
        
        yield event.plain_result(report)
    
    # 清空发送记录
    @cmd_group_sender.command("clear_records")
    async def cmd_clear_records(self, event: AstrMessageEvent):
        '''清空发送记录'''
        if not await self.context.check_permission(event, "admin"):
            yield event.plain_result("权限不足，只有管理员可以使用此命令")
            return
        
        self.records = []
        self.save_records()
        
        yield event.plain_result("已清空所有发送记录")
    
    # 帮助命令
    @cmd_group_sender.command("help")
    async def cmd_help(self, event: AstrMessageEvent):
        '''显示帮助信息'''
        help_text = """群发消息插件使用帮助:

基本命令:
/groupsend - 立即向所有配置的群发送随机内容

配置命令:
/groupsender config - 查看当前配置
/groupsender add_content <内容> - 添加随机内容
/groupsender del_content <索引> - 删除随机内容
/groupsender add_group <群号> - 添加目标群
/groupsender del_group <群号> - 删除目标群
/groupsender set_interval <秒数> - 设置发送间隔
/groupsender set_schedule <on/off> [daily/interval] [HH:MM] [天数] - 设置定时发送

记录命令:
/groupsender records [数量] - 查看发送记录
/groupsender clear_records - 清空发送记录

注意: 所有命令仅管理员可用
"""
        yield event.plain_result(help_text)
    
    # 监听群消息，用于收集群号
    @filter.event_message_type(MessageType.GROUP)  # 使用 MessageType 替代 EventMessageType
    async def on_group_message(self, event: AstrMessageEvent):
        '''监听群消息，用于收集群号'''
        # 这里不做任何处理，只是为了在后续版本中可能添加的功能预留
        pass
    
    async def terminate(self):
        '''插件被卸载/停用时调用'''
        # 取消定时任务
        if self.scheduled_task and not self.scheduled_task.done():
            self.scheduled_task.cancel()
        self.logger.info("群发消息插件已停用")
            
