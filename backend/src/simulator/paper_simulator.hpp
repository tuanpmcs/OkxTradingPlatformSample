#pragma once

#include <cstdint>
#include <optional>
#include <string>

struct PaperSimulatorConfig
{
	double initial_cash_usd{100000.0};
	double trade_notional_usd{1000.0};
	double fee_bps{1.0};
	double slippage_bps{0.5};
	std::int64_t max_hold_ms{2000};
	double min_predicted_return{0.0};
};

struct PaperSimulatorSnapshot
{
	double cash_usd{0.0};
	double position_qty{0.0};
	double entry_price{0.0};
	double mark_price{0.0};
	double equity_usd{0.0};
	double realized_pnl_usd{0.0};
	double unrealized_pnl_usd{0.0};
	double fees_paid_usd{0.0};
	std::uint64_t trade_count{0};
	std::uint64_t win_count{0};
	std::uint64_t loss_count{0};
};

struct PaperSimulatorEvent
{
	std::string action;
	double		fill_price{0.0};
	double		fill_qty{0.0};
	double		realized_pnl_usd{0.0};
};

class PaperSimulator
{
public:
	explicit PaperSimulator(PaperSimulatorConfig cfg);

	std::optional<PaperSimulatorEvent> on_signal(std::int64_t ts_ms,
												 double		  mid_price,
												 const std::string& signal,
												 double		  predicted_return);
	std::optional<PaperSimulatorEvent> close_all(std::int64_t ts_ms, double mid_price, const char* reason);
	PaperSimulatorSnapshot			   snapshot() const;

private:
	std::optional<PaperSimulatorEvent> open_position(std::int64_t ts_ms, double mid_price, bool long_side);
	std::optional<PaperSimulatorEvent> close_position(std::int64_t ts_ms, double mid_price, const char* reason);
	static double						apply_slippage(double mid_price, bool buy_side, double slippage_bps);
	double								equity_usd() const;

private:
	PaperSimulatorConfig _cfg;
	double _cash_usd{0.0};
	double _position_qty{0.0};
	double _entry_price{0.0};
	double _last_mark_price{0.0};
	std::int64_t _position_open_ts_ms{0};
	double _realized_pnl_usd{0.0};
	double _fees_paid_usd{0.0};
	std::uint64_t _trade_count{0};
	std::uint64_t _win_count{0};
	std::uint64_t _loss_count{0};
};
