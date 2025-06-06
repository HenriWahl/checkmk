//
// check_mk_service.cpp : This file contains ONLY the 'main' function.
//
// Precompiled
#include "pch.h"

#include "check_mk_service.h"

#include <iostream>

#include "common/cfg_info.h"
#include "common/cmdline_info.h"
#include "cstdint"  // for int64_t, uint32_t, uint64_t
#include "providers/perf_counters_cl.h"
#include "wnx/cfg.h"
#include "wnx/cma_core.h"
#include "wnx/install_api.h"
#include "wnx/logger.h"
#include "wnx/on_start.h"  // for AppType, OnStartApp, AppType::exe, AppType::srv
#include "wnx/windows_service_api.h"

using namespace std::chrono_literals;
using XLOG::Colors;

namespace cma::cmdline {

void PrintBlock(std::string_view title, Colors title_color,
                const std::function<std::string()> &formatter) {
    xlog::sendStringToStdio(title.data(), title_color);
    const auto out = formatter();
    printf("%s", out.data());
}

void PrintMain() {
    PrintBlock("Normal Usage:\n", Colors::green, [] {
        return fmt::format(
            "\t{1} <{2}|{3}|{4}|{5}|{6}>\n"
            "\t{2:<{0}} - generates test output\n"
            "\t{3:<{0}} - version of the Agent\n"
            "\t{4:<{0}} - reload configuration files of the Agent\n"
            "\t{5:<{0}} - remove Legacy Agent if installed\n"
            "\t{6:<{0}} - usage\n",
            kParamShift,
            kServiceExeName,  // service name from th project definitions
            // first Row
            kLegacyTestParam, kVersionParam, kReloadConfigParam,
            kRemoveLegacyParam, kHelpParam);
    });
}

void PrintAgentUpdater() {
    PrintBlock("Agent Updater Usage:\n", Colors::green, [] {
        return fmt::format(
            "\t{1} <{2}|{3}> [args]\n"
            "\t{2}|{3:<{0}} - register Agent using plugins\\cmk_update_agent.checmk.py\n",
            kParamShift,
            kServiceExeName,  // service name from the project definitions
            // first Row
            kUpdaterParam, kCmkUpdaterParam);
    });
}

void PrintSelfCheck() {
    PrintBlock("Self Checking:\n", Colors::cyan, [] {
        return fmt::format(
            "\t{1} {2} <{3}|{4}|{5} [number of seconds]>\n"
            "\t{2:<{0}} - check test\n"
            "\t\t{3:<{0}} - main thread test\n"
            "\t\t{4:<{0}} - simple self test of internal and external transport\n"
            "\t\t{5:<{0}} - simulates periodical connection from Checkmk Site, for example '{1} {2} {5} 13'\n",
            kParamShift, kServiceExeName, kCheckParam, kCheckParamMt,
            kCheckParamIo, kCheckParamSelf);
    });
}

void PrintAdHoc() {
    PrintBlock("Ad Hoc Testing:\n", Colors::cyan, [] {
        return fmt::format(
            "\t{1} <{2}> [{3}|{4}]\n"
            "\t{2:{0}} - run as application (adhoc mode)\n"
            "\t\t{3:{0}} - send important messages on stdio\n"
            "\t\t{4:{0}} - send ALL messages on stdio\n",
            kParamShift,  //
            kServiceExeName,
            std::string(kExecParam) + "|" + std::string(kAdhocParam),  //
            kExecParamShowWarn, kExecParamShowAll);
    });
}

// obsolete
void PrintLegacyTesting() {
    PrintBlock("Classic/Legacy Testing:\n", Colors::cyan, [] {
        return fmt::format(
            "\t{1} {2}\n"
            "\t{2:{0}} - legacy(standard) test\n",
            kParamShift,
            kServiceExeName,  // service name from th project definitions
            kLegacyTestParam);
    });
}

void PrintReinstallWATO() {
    PrintBlock(
        "Restore WATO Configuration(only for experienced users):\n",
        Colors::pink, [] {
            return fmt::format(
                "\t{1} {2}\n"
                "\t{2:{0}} - agent tries to restore configuration created by WATO(bakery)\n",
                kParamShift,
                kServiceExeName,  // service name from th project definitions
                kRestoreParam);
        });
}

void PrintInstallUninstall() {
    PrintBlock(
        "Install or remove service(only for experienced users):\n",
        Colors::pink, [] {
            return fmt::format(
                "\t{1} <{2}|{3}>\n"
                "\t{2:<{0}} - install as a service, Administrative Rights are required\n"
                "\t{3:<{0}} - remove service, Administrative Rights are required\n",
                kParamShift,
                kServiceExeName,  // service name from th project definitions
                // first Row
                kInstallParam, kRemoveParam);
        });
}

void PrintShowConfig() {
    PrintBlock("Display Config and Environment Variables:\n", Colors::cyan, [] {
        return fmt::format(
            "\t{1} {2} [section]\n"
            "\t{2:<{0}} - show configuration parameters\n"
            "\tsection - optional parameter like global or ps\n"
            "\t\tExample: {1} {2} fileinfo\n",
            kParamShift,
            kServiceExeName,  // service name from th project definitions
            kShowConfigParam);
    });
}

void PrintRealtimeTesting() {
    PrintBlock("Realtime Testing:\n", Colors::cyan, [] {
        return fmt::format(
            "\t{1} {2}\n"
            "\t{2:{0}} - test realtime data with all sections and encryption\n",
            kParamShift,
            kServiceExeName,  // service name from th project definitions
            kRealtimeParam);
    });
}

void PrintCvt() {
    PrintBlock(
        "Convert Legacy Agent Ini File into Agent Yml file:\n", Colors::pink,
        [] {
            return fmt::format(
                "\t{0} {1} [{2}] <inifile> [yamlfile]\n"
                "\tinifile - from Legacy Agent\n"
                "\tyamlfile - name of an output file\n"
                "\t{2} - display output\n",
                kServiceExeName,  // service name from th project definitions
                kCvtParam, kCvtParamShow);
        });
}

void PrintLwaActivate() {
    PrintBlock("Activate/Deactivate Legacy Agent:\n", Colors::pink, [] {
        return fmt::format(
            "\t{1} <{2}|{3}>\n"
            "\t{2:{0}} - stop and deactivate legacy agent\n"
            "\t{3:{0}} - activate and start legacy agent(only for testing)\n",
            kParamShift,
            kServiceExeName,  // service name from th project definitions
            kStopLegacyParam, kStartLegacyParam);
    });
}

void PrintFirewall() {
    PrintBlock("Configure Firewall Rule:\n", Colors::pink, [] {
        return fmt::format(
            "\t{1} [{2}|{3}]\n"
            "\t{2:{0}} - configure firewall\n"
            "\t{3:{0}} - clear firewall configuration\n",
            kParamShift, kFwParam, kFwConfigureParam, kFwClearParam);
    });
}

void PrintUpgrade() {
    PrintBlock("Upgrade Legacy Agent(migration):\n", Colors::pink, [] {
        return fmt::format(
            "\t{1} {2} [{3}]\n"
            "\t{2:{0}} - upgrading/migration\n"
            "\t\t{3:{0}} - upgrading/migration is forced( file '{2}' is ignored)\n",
            kParamShift,
            kServiceExeName,  // service name from th project definitions
            kUpgradeParam, kUpgradeParamForce, cfg::files::kUpgradeProtocol);
    });
}

void PrintCap() {
    PrintBlock(
        "Install Bakery Files and plugins.cap in install folder:\n",
        Colors::pink, [] {
            return fmt::format(
                "\t{0} {1}\n",
                kServiceExeName,  // service name from th project definitions
                kCapParam);
        });
}

void PrintSectionTesting() {
    PrintBlock("Test sections individually:\n", Colors::pink, [] {
        return fmt::format(
            "\t{1} {2} {3} [{4} [{5}]] \n"
            "\t\t{3:{0}} - any section name(df, fileinfo and so on)\n"
            "\t\t{4:{0}} - pause between tests in seconds, count of tests are infinite. 0 - test once\n"
            "\t\t{5:{0}} - log output on the stdio\n"
            "\t\t\t example: '{1} {2} df 5 {5}'\n"
            "\t\t\t test section df infinitely long with pause 5 seconds and log output on stdio\n",
            kParamShift,
            kServiceExeName,  // service name from th project definitions
            kSectionParam, "any_section", "number_of_seconds",
            kSectionParamShow);
    });
}

// print short info about usage plus potential comment about error
void ServiceUsage(std::wstring_view comment) {
    XLOG::setup::ColoredOutputOnStdio(true);
    XLOG::setup::DuplicateOnStdio(true);
    if (!comment.empty()) {
        xlog::sendStringToStdio(wtools::ToUtf8(comment).data(), Colors::red);
    }

    try {
        PrintMain();
        PrintAgentUpdater();
        PrintSelfCheck();
        PrintAdHoc();
        PrintRealtimeTesting();
        PrintShowConfig();
        PrintCvt();
        PrintLwaActivate();
        PrintFirewall();
        PrintUpgrade();
        PrintCap();
        PrintSectionTesting();
        PrintInstallUninstall();
        PrintReinstallWATO();
    } catch (const std::exception &e) {
        XLOG::l("Exception is '{}'", e.what());  //
    }

    // undocumented
    // -winperf ....... command line for runperf
}

}  // namespace cma::cmdline

namespace cma {
AppType AppDefaultType() {
    return GetModus() == Modus::service ? AppType::srv : AppType::exe;
}

namespace {

template <typename T>
auto ToInt(const T value, int dflt) noexcept {
    try {
        return std::stoi(value);
    } catch (const std::exception & /*exc*/) {
        return dflt;
    }
}

template <typename T>
auto ToInt(const T value) noexcept {
    return ToInt(value, 0);
}

template <typename T>
auto ToUInt64(const T value, uint64_t dflt) noexcept {
    try {
        return std::stoull(value);
    } catch (const std::exception & /*exc*/) {
        return dflt;
    }
}

template <typename T>
auto ToUInt64(const T value) noexcept {
    return ToUInt64(value, 0);
}

template <typename T>
auto ToInt64(const T value, int64_t dflt) noexcept {
    try {
        return std::stoll(value);
    } catch (const std::exception & /*exc*/) {
        return dflt;
    }
}

template <typename T>
auto ToInt64(const T value) noexcept {
    return ToInt64(value, 0);
}

template <typename T>
auto ToUInt(const T value, uint32_t dflt) noexcept {
    try {
        return static_cast<uint32_t>(std::stoul(value));
    } catch (const std::exception & /*exc*/) {
        return dflt;
    }
}

template <typename T>
auto ToUInt(const T value) noexcept {
    return ToUInt(value, 0);
}
}  // namespace

// on check
int CheckMainService(const std::wstring &param, int interval) {
    auto what = wtools::ToUtf8(param);

    if (what == cmdline::kCheckParamMt) {
        return srv::TestMt();
    }

    if (what == cmdline::kCheckParamIo) {
        return srv::TestIo();
    }

    if (what == cmdline::kCheckParamSelf) {
        return srv::TestMainServiceSelf(interval);
    }

    XLOG::setup::DuplicateOnStdio(true);
    XLOG::setup::ColoredOutputOnStdio(true);
    XLOG::l("Unsupported second parameter '{}'\n\t Allowed {}, {} or {}", what,
            cmdline::kCheckParamIo, cmdline::kCheckParamMt,
            cmdline::kCheckParamSelf);

    return 0;
}

namespace srv {
int RunService(std::wstring_view app_name) {
    details::SetModus(Modus::service);  // we know that we are service

    const auto ret = ServiceAsService(app_name, 1000ms, [] {
        // Auto Update when  MSI file is located by specified address
        // this part of code have to be tested manually
        auto [command, started] = install::CheckForUpdateFile(
            install::kDefaultMsiFileName,    // file we are looking for
            cfg::GetUpdateDir(),             // dir with file
            install::UpdateProcess::execute  // operation if file found
        );

        if (started) {
            XLOG::l.i(
                "Install process with command '{}' was initiated - waiting for restart",
                wtools::ToUtf8(command));
        }

        return true;
    });

    if (ret == 0) {
        cmdline::ServiceUsage(L"");
    }

    return ret == 0 ? 0 : 1;
}
}  // namespace srv

namespace {
void WaitForPostInstall() {
    if (!install::IsPostInstallRequired()) {
        return;
    }

    std::cout << "Finalizing installation, please wait";
    int count = 0;

    do {
        std::this_thread::sleep_for(1s);
        std::cout << ".";
        ++count;
        if (count > 240) {
            std::cout << "Service is failed or nor running";
            ::exit(73);  // NOLINT
        }
    } while (install::IsPostInstallRequired());
}

int ProcessWinperf(const std::vector<std::wstring> &args) {
    // Two possibilities:
    // @file winperf file:a.txt id:12345 timeout:20 238:processor
    //       winperf file:a.txt id:12345 timeout:20 238:processor
    int offset = 0;
    if (args[0][0] == '@') {
        try {
            const std::filesystem::path p{args[0].c_str() + 1};
            XLOG::setup::ChangeLogFileName(wtools::ToUtf8(p.wstring()));
            XLOG::setup::EnableDebugLog(true);
            XLOG::setup::EnableTraceLog(true);
            XLOG::d.i("winperf started");
            offset++;
        } catch (const std::exception & /*e*/) {
            // nothing can be done here:
            // command line is bad, log file probably too
            return 1;
        }
    }

    auto parsed =
        exe::cmdline::ParseExeCommandLine({args.begin() + offset, args.end()});

    if (parsed.error_code != 0) {
        XLOG::l("Invalid parameters in command line [{}]", parsed.error_code);
        return 1;
    }

    const auto &port = args[offset + 1];
    std::vector<std::wstring_view> counters;
    for (size_t i = 4 + offset; i < args.size(); i++) {
        if (std::wstring(L"#") == args[i]) {
            break;
        }
        counters.emplace_back(args[i]);
    }

    return provider::RunPerf(parsed.name, port, parsed.id_val,
                             ToInt(parsed.timeout_val, 20), counters);
}
}  // namespace

// #TODO Function is overcomplicated
// we want to test main function too.
// so we have main, but callable
int MainFunction(int argc, wchar_t const *argv[]) {
    std::set_terminate([] {
        //
        XLOG::details::LogWindowsEventCritical(999, "Win Agent is Terminated.");
        XLOG::l.bp("Win Agent is Terminated.");
        abort();
    });

    if (argc == 1) {
        return srv::RunService(argv[0]);
    }

    WaitForPostInstall();

    std::string param(wtools::ToUtf8(argv[1]));
    if (param == wtools::ToUtf8(exe::cmdline::kRunOnceParam)) {
        // NO READING FROM CONFIG. This is intentional
        //
        // -runonce @file winperf file:a.txt id:12345 timeout:20 238:processor
        // -runonce winperf file:a.txt id:12345 timeout:20 238:processor
        std::vector<std::wstring> args;
        for (int i = 2; i < argc; i++) {
            args.emplace_back(argv[i]);
        }
        return ProcessWinperf(args);
    }

    using namespace cmdline;

    OnStartApp();  // path from EXE

    if (param == kInstallParam) {
        return srv::InstallMainService();
    }
    if (param == kRemoveParam) {
        return srv::RemoveMainService();
    }

    if (param == kCheckParam) {
        std::wstring param_next = argc > 2 ? argv[2] : L"";
        auto interval = argc > 3 ? ToInt(argv[3]) : 0;
        return CheckMainService(param_next, interval);
    }

    if (param == kLegacyTestParam) {
        return srv::TestLegacy();
    }

    if (param == kRestoreParam) {
        return srv::RestoreWatoConfig();
    }

    if (param == kExecParam || param == kAdhocParam) {
        std::string second_param{argc > 2 ? wtools::ToUtf8(argv[2]) : ""};

        auto log_on_screen = srv::StdioLog::no;
        if (second_param == kExecParamShowAll) {
            log_on_screen = srv::StdioLog::extended;
        } else if (second_param == kExecParamShowWarn) {
            log_on_screen = srv::StdioLog::yes;
        } else if (second_param == kExecParamIntegration) {
            if (tools::win::GetEnv(env::integration_base_dir).empty()) {
                fmt::print(
                    L"Integration is requested, but env var '{}' is absent\n",
                    env::integration_base_dir);
                ::exit(12);  // NOLINT
            }
            details::SetModus(Modus::integration);
        }

        return srv::ExecMainService(log_on_screen);
    }
    if (param == kRealtimeParam) {
        return srv::ExecRealtimeTest(true);
    }
    if (param == kSkypeParam) {
        return srv::ExecSkypeTest();
    }
    if (param == kResetOhm) {
        return srv::ExecResetOhm();
    }

    if (param == kStopLegacyParam) {
        return srv::ExecStopLegacy();
    }
    if (param == kStartLegacyParam) {
        return srv::ExecStartLegacy();
    }
    if (param == kCapParam) {
        return srv::ExecCap();
    }

    if (param == kVersionParam) {
        return srv::ExecVersion();
    }

    if (param == kUpdaterParam || param == kCmkUpdaterParam) {
        std::vector<std::wstring> params;
        for (int k = 2; k < argc; k++) {
            params.emplace_back(argv[k]);
        }

        return srv::ExecCmkUpdateAgent(params);
    }

    if (param == kPatchHashParam) {
        return srv::ExecPatchHash();
    }

    if (param == kShowConfigParam) {
        std::wstring second_param = argc > 2 ? argv[2] : L"";
        return srv::ExecShowConfig(wtools::ToUtf8(second_param));
    }

    if (param == kUpgradeParam) {
        std::wstring second_param = argc > 2 ? argv[2] : L"";
        return srv::ExecUpgradeParam(
            second_param == wtools::ConvertToUtf16(kUpgradeParamForce));
    }
    // #TODO make a function
    if (param == kCvtParam) {
        if (argc > 2) {
            auto diag = tools::CheckArgvForValue(argc, argv, 2, kCvtParamShow)
                            ? srv::StdioLog::yes
                            : srv::StdioLog::no;

            auto pos = diag == srv::StdioLog::yes ? 3 : 2;
            if (argc <= pos) {
                ServiceUsage(std::wstring(L"inifile is mandatory to call ") +
                             wtools::ConvertToUtf16(kCvtParam) + L"\n");
                return 2;
            }

            std::wstring ini = argc > pos ? argv[pos] : L"";
            std::wstring yml = argc > pos + 1 ? argv[pos + 1] : L"";

            return srv::ExecCvtIniYaml(ini, yml, diag);
        }

        ServiceUsage(std::wstring(L"Invalid count of parameters for ") +
                     wtools::ConvertToUtf16(kCvtParam) + L"\n");
        return 2;
    }

    if (param == kFwParam) {
        if (argc <= 2) {
            return srv::ExecFirewall(srv::FwMode::show, argv[0], {});
        }

        if (tools::CheckArgvForValue(argc, argv, 2, kFwConfigureParam)) {
            return srv::ExecFirewall(srv::FwMode::configure, argv[0],
                                     srv::kAppFirewallRuleName);
        }

        if (tools::CheckArgvForValue(argc, argv, 2, kFwClearParam)) {
            return srv::ExecFirewall(srv::FwMode::clear, argv[0],
                                     srv::kAppFirewallRuleName);
        }

        ServiceUsage(std::wstring(L"Invalid parameter for ") +
                     wtools::ConvertToUtf16(kFwParam) + L"\n");
        return 2;
    }

    if (param == kSectionParam && argc > 2) {
        std::wstring section = argv[2];
        int delay = argc > 3 ? ToInt(argv[3]) : 0;
        auto diag = tools::CheckArgvForValue(argc, argv, 4, kSectionParamShow)
                        ? srv::StdioLog::yes
                        : srv::StdioLog::no;
        return srv::ExecSection(section, delay, diag);
    }

    if (param == kCapExtractParam && argc > 3) {
        std::wstring file = argv[2];
        std::wstring to = argv[3];
        return srv::ExecExtractCap(file, to);
    }

    if (param == kReloadConfigParam) {
        srv::ExecReloadConfig();
        return 0;
    }

    if (param == kUninstallAlert) {
        XLOG::l.i("UNINSTALL ALERT");
        srv::ExecUninstallAlert();
        return 0;
    }

    if (param == kRemoveLegacyParam) {
        srv::ExecRemoveLegacyAgent();
        return 0;
    }

    if (param == kHelpParam) {
        ServiceUsage(L"");
        return 0;
    }

    auto text = std::wstring(L"Provided Parameter \"") +
                wtools::ConvertToUtf16(param) + L"\" is not allowed\n";

    ServiceUsage(text);
    return 13;
}
}  // namespace cma

#if !defined(CMK_TEST)
int wmain(int argc, wchar_t const *argv[]) {
    return cma::MainFunction(argc, argv);
}
#endif
