@echo off
title JARVIS Calibration Scheduler Setup
echo ========================================================
echo   JARVIS Automatic Calibration Scheduler Setup
echo ========================================================
echo.
echo This will create a Windows Scheduled Task that runs
echo JARVIS calibration automatically every Sunday at 1:00 PM.
echo.
echo The task will:
echo   - Run "py run_calibration.py --apply" weekly
echo   - Auto-tune validation thresholds based on usage data
echo   - Save reports to calibration_report.json
echo   - Run as soon as possible if the scheduled time was missed
echo.
echo Press any key to continue, or Ctrl+C to cancel...
pause >nul

echo.
echo Creating scheduled task...

:: Get the current directory
set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

:: Create the scheduled task with XML for advanced options
:: This enables "run missed task" (StartWhenAvailable) which the basic
:: schtasks command doesn't support
set "TASK_XML=<?xml version="1.0" encoding="UTF-16"?><Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"><RegistrationInfo><Description>Runs JARVIS calibration weekly to auto-tune validation thresholds</Description></RegistrationInfo><Triggers><CalendarTrigger><StartBoundary>2026-01-01T13:00:00</StartBoundary><Enabled>true</Enabled><ScheduleByWeek><DaysOfWeek><Sunday/></DaysOfWeek><WeeksInterval>1</WeeksInterval></ScheduleByWeek></CalendarTrigger></Triggers><Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals><Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><AllowHardTerminate>true</AllowHardTerminate><StartWhenAvailable>true</StartWhenAvailable><RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable><AllowStartOnDemand>true</AllowStartOnDemand><Enabled>true</Enabled><Hidden>false</Hidden><RunOnlyIfIdle>false</RunOnlyIfIdle><WakeToRun>false</WakeToRun><ExecutionTimeLimit>PT30M</ExecutionTimeLimit><Priority>7</Priority></Settings><Actions Context="Author"><Exec><Command>py</Command><Arguments>"%PROJECT_DIR%\run_calibration.py" --apply</Arguments><WorkingDirectory>%PROJECT_DIR%</WorkingDirectory></Exec></Actions></Task>"

:: Register the task using XML
schtasks /create /tn "JARVIS_Weekly_Calibration" /xml "%TEMP%\jarvis_task.xml" /f 2>nul
echo %TASK_XML% > "%TEMP%\jarvis_task.xml"
schtasks /create /tn "JARVIS_Weekly_Calibration" /xml "%TEMP%\jarvis_task.xml" /f

if %ERRORLEVEL% equ 0 (
    echo.
    echo ========================================================
    echo   SUCCESS! Scheduled task created.
    echo ========================================================
    echo.
    echo Task name: JARVIS_Weekly_Calibration
    echo Schedule: Every Sunday at 1:00 PM
    echo Command:  py run_calibration.py --apply
    echo Missed:   Runs ASAP if PC was off at scheduled time
    echo.
    echo To verify: Open Task Scheduler and look for "JARVIS_Weekly_Calibration"
    echo To remove: schtasks /delete /tn "JARVIS_Weekly_Calibration" /f
    echo.
) else (
    echo.
    echo ========================================================
    echo   ERROR: Could not create scheduled task.
    echo ========================================================
    echo.
    echo Possible causes:
    echo   - Not running as Administrator (try right-click -^> Run as admin)
    echo   - Task already exists (it was recreated with /f flag)
    echo.
)

:: Clean up temp file
del "%TEMP%\jarvis_task.xml" 2>nul

echo Press any key to exit...
pause >nul
