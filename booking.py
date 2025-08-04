import logging
import os
import random
import re
import time
from datetime import datetime, timedelta

from playwright.sync_api import sync_playwright

# 配置日志记录，保存到 booking.log 文件中
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('booking.log', mode='w', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

class LightningFastBooking:
    def __init__(self):
        self.username = os.getenv('BOOKING_USERNAME')
        self.password = os.getenv('BOOKING_PASSWORD')

        if not self.username or not self.password:
            error_message = (
                "错误：未找到 BOOKING_USERNAME 或 BOOKING_PASSWORD。\n"
                " - 如果在 GitHub Actions 运行, 请在仓库的 Settings > Secrets and variables > Actions 中设置它们。\n"
                " - 如果在本地运行, 请将它们设置为环境变量。"
            )
            raise ValueError(error_message)
        self.venue_name = "望江西区网球场"
        self.courts = ["1号场", "2号场", "3号场"]
        self.time_slots = ["18:00-19:00", "19:00-20:00", "20:00-21:00"]
        self.target_time = "08:30:00:000"
        self.is_ci = os.getenv('GITHUB_ACTIONS') == 'true'

    def random_delay(self, profile='normal'):
        """分级延迟：'normal'用于准备阶段，'fast'用于抢票的 crítico 阶段。"""
        if self.is_ci:
            time.sleep(0.2)
            return

        if profile == 'fast':
            min_sec, max_sec = 0.1, 0.3
        else: # 'normal'
            min_sec, max_sec = 0.5, 1.2
        
        delay = random.uniform(min_sec, max_sec)
        time.sleep(delay)

    def wait_until_target_time(self):
        """等待到目标时间才开始执行（精确到毫秒）"""
        if self.is_ci:
            logging.info("CI环境，直接执行预约...")
            return
            
        now = datetime.now()
        time_parts = self.target_time.split(':')
        target = now.replace(
            hour=int(time_parts[0]), 
            minute=int(time_parts[1]), 
            second=int(time_parts[2]), 
            microsecond=int(time_parts[3]) * 1000
        )
        
        if now >= target:
            target += timedelta(days=1)
        
        logging.info(f"准备工作完成，等待目标时间: {target.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}")
        
        while datetime.now() < target:
            time.sleep(0.001) # 毫秒级自旋等待
        
        logging.info("⏰ 时间到！开始执行抢票...")

    def wait_and_click(self, page, selector_list, timeout=5000):
        for selector in selector_list:
            try:
                element = page.locator(selector).first
                element.wait_for(state='visible', timeout=timeout)
                element.scroll_into_view_if_needed()
                # 在关键的抢票阶段使用快速延迟
                delay_profile = 'fast' if page.url.endswith('booking') else 'normal'
                self.random_delay(delay_profile)
                element.click()
                logging.info(f"成功点击元素: {selector}")
                return True
            except Exception:
                logging.warning(f"选择器 {selector} 点击失败，尝试下一个...")
                continue
        logging.error(f"所有选择器均无法点击: {selector_list}")
        return False

    def do_login(self, page):
        logging.info("处理登录...")
        if not self.wait_and_click(page, ['text="校外人员登录"']):
             raise Exception("点击'校外人员登录'失败")
        
        if self.username and self.password:
            page.locator('input[type="text"]').fill(self.username)
            page.locator('input[type="password"]').fill(self.password)
            self.random_delay('normal')
            logging.info("已填写登录信息")
            
            if not self.wait_and_click(page, ['uni-button:has-text("立即登录")']):
                 raise Exception("点击'立即登录'按钮失败")
            logging.info("登录成功")
        else:
            logging.warning("未设置用户名或密码，跳过登录步骤")
        
        page.wait_for_load_state('networkidle', timeout=10000)

    def _login_and_prepare(self, page):
        """第一阶段：在关键时间前完成登录，并导航至可预订页面"""
        logging.info("--- Phase 1: Pre-login and Preparation ---")
        logging.info("打开场地预约主页...")
        page.goto("http://cgzx.scu.edu.cn/venue/", wait_until="domcontentloaded")
        
        self.do_login(page)

        logging.info(f"选择场馆: {self.venue_name}")
        if not self.wait_and_click(page, [f'text="{self.venue_name}"']):
            raise Exception(f"选择场馆 '{self.venue_name}' 失败")

        self.random_delay('normal')

        booking_selectors = ['uni-button:has-text("场馆预约")', 'text=场馆预约', 'uni-button']
        logging.info(f"点击场馆预约按钮...")
        if not self.wait_and_click(page, booking_selectors):
            raise Exception("点击'场馆预约'按钮失败")
        
        logging.info("--- Phase 1 Complete: Logged in and on the booking page. ---")

    def _execute_booking(self, page):
        """第二阶段：执行时间敏感的预订操作，遍历所有场地和时间组合"""
        logging.info("--- Phase 2: Critical Booking Execution ---")
        
        # 1. 选择日期 (只需一次)
        logging.info("选择明天日期...")
        tomorrow = (datetime.now() + timedelta(days=1)).day
        date_selectors = [f'text=明天', f'text=/-{tomorrow:02d}/', f'text=/{tomorrow:02d}/']
        if not self.wait_and_click(page, date_selectors):
            raise Exception("选择明天日期失败")
        self.random_delay('fast')

        # 2. 创建并随机化所有场地和时间段的组合
        all_combinations = [(court, slot) for court in self.courts for slot in self.time_slots]
        random.shuffle(all_combinations)
        logging.info(f"将按随机顺序尝试 {len(all_combinations)} 种预订组合: {all_combinations}")

        # 3. 遍历所有组合进行尝试
        for court, time_slot in all_combinations:
            try:
                logging.info(f"--- 正在尝试组合: 场地[{court}], 时间[{time_slot}] ---")
                
                # a. 选择场地 (切换tab)
                court_selectors = [f'uni-text:has-text("{court}")', f'text={court}']
                if not self.wait_and_click(page, court_selectors, timeout=1500):
                    logging.warning(f"无法点击场地 '{court}' 的tab，跳过此组合。")
                    continue
                self.random_delay('fast')

                # b. 选择时间段
                end_time = time_slot.split('-')[1]
                start_hour_text = time_slot.split('-')[0].split(':')[0]
                time_regex = re.compile(f"{start_hour_text}:00 - {end_time}.*￥")
                
                page.get_by_text(time_regex).first.click(timeout=1000)
                self.random_delay('fast')

                # c. 点击 '确定' 并验证
                page.locator('uni-button:has-text("确定")').first.click(timeout=1000)
                page.locator('uni-button:has-text("提交订单")').first.wait_for(state='visible', timeout=2000)
                
                logging.info(f"✅ 成功锁定组合: 场地[{court}], 时间[{time_slot}]。")
                
                # d. 提交最终订单
                if not self.wait_and_click(page, ['uni-button:has-text("提交订单")']):
                    logging.warning("锁定后提交失败，可能被抢占。尝试下一个组合...")
                    continue

                # e. 检查结果并支付
                success = self.check_result(page)
                if success:
                    self.go_to_payment(page)
                
                return success

            except Exception as e:
                error_summary = str(e).split('\n')[0]
                logging.warning(f"组合 [{court} / {time_slot}] 尝试失败: {error_summary}. 尝试下一个...")
                continue
        
        raise Exception("已尝试所有场地和时间组合，未能成功预订。")

    def check_result(self, page):
        logging.info("检查预约结果...")
        try:
            success_locator = page.locator('text=/预约成功|提交成功/').first
            success_locator.wait_for(state='visible', timeout=4000)
            logging.info(f"✅ 预约成功！消息: '{success_locator.text_content(timeout=500).strip()}'")
            return True
        except Exception:
            logging.info("未检测到成功信息，正在检查是否存在错误提示...")
            try:
                error_locator = page.locator('text=/失败|错误|超限|频繁|取消.*次|已达上限/').first
                error_locator.wait_for(state='visible', timeout=1000)
                error_message = error_locator.text_content(timeout=500)
                logging.error(f"❌ 预约失败，检测到错误信息: '{error_message.strip()}'")
                return False
            except Exception:
                logging.warning("⚠️ 预约结果不确定，未找到明确的成功或失败信息。")
                return False

    def go_to_payment(self, page):
        logging.info("尝试点击 '去支付'...")
        payment_selectors = ['text="去支付"']
        if self.wait_and_click(page, payment_selectors, timeout=5000):
            logging.info("已点击 '去支付'。请手动完成支付。")
            return True
        else:
            logging.warning("'去支付' 按钮未找到或无法点击。请手动处理。")
            return False

    def run(self):
        """总调度函数，编排两阶段执行流程"""
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.is_ci,
                args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.15(0x18000f2e) NetType/WIFI Language/zh_CN",
                viewport={"width": 390, "height": 844},
                locale="zh-CN",
                ignore_https_errors=True,
            )
            page = context.new_page()
            
            try:
                self._login_and_prepare(page)
                self.wait_until_target_time()
                
                booking_start_time = time.time()
                success = self._execute_booking(page)
                
                booking_time = time.time() - booking_start_time
                logging.info(f"关键预定耗时: {booking_time:.3f}秒")
                return success
                
            except Exception as e:
                logging.error(f"❌ 预约流程发生意外错误: {str(e)}")
                timestamp = int(time.time())
                screenshot_path = f"error_{timestamp}.png"
                try:
                    page.screenshot(path=screenshot_path, full_page=True)
                    logging.info(f"错误截图已保存: {screenshot_path}")
                except Exception as ex:
                    logging.error(f"无法保存截图: {ex}")
                return False
            finally:
                if not self.is_ci:
                    print("\n💡 浏览器将保持打开状态，您可以手动查看预约详情")
                    input("💡 按 Enter 键关闭浏览器...")
                browser.close()

if __name__ == "__main__":
    logging.info("🚀 启动两阶段预约脚本...")
    booking = LightningFastBooking()
    logging.info(f"⏰  目标时间: {booking.target_time}")
    logging.info(f"🎯  目标场地: {booking.venue_name} - {booking.courts}")
    logging.info(f"ช่วง  目标时段: {booking.time_slots}")
    logging.info("="*50)
    
    success = booking.run()
    
    if success:
        logging.info("🎉 预约流程全部完成！")
    else:
        logging.error("⚠️ 预约过程中遇到问题，请检查日志 booking.log 和截图")
