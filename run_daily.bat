@echo off
REM AITrader 每日自动交易脚本
REM 使用前请先编辑 .env 文件配置 API 密钥

cd /d %~dp0

REM 从 .env 加载环境变量（如果有）
if exist .env (
    for /f "tokens=1,2 delims==" %%a in (.env) do (
        set %%a=%%b
    )
)

echo [%date% %time%] === Daily Run === >> logs\trading.log
python cli.py run >> logs\trading.log 2>&1
echo [%date% %time%] Done >> logs\trading.log
