#include "simulator/paper_simulator.hpp"

#include <algorithm>
#include <cmath>

namespace
{
constexpr double kBpsDenominator = 10000.0;
}

PaperSimulator::PaperSimulator(PaperSimulatorConfig cfg)
	: _cfg(std::move(cfg))
	, _cash_usd(_cfg.initial_cash_usd)
{
}

std::optional<PaperSimulatorEvent> PaperSimulator::on_signal(std::int64_t		  ts_ms,
															 double				  mid_price,
															 const std::string& signal,
															 double				  predicted_return)
{
	if (!(mid_price > 0.0))
	{
		return std::nullopt;
	}
	_last_mark_price = mid_price;

	if (_position_qty != 0.0 && _cfg.max_hold_ms > 0 && ts_ms - _position_open_ts_ms >= _cfg.max_hold_ms)
	{
		return close_position(ts_ms, mid_price, "max_hold");
	}

	const bool want_long = signal == "LONG" && predicted_return >= _cfg.min_predicted_return;
	const bool want_short = signal == "SHORT" && -predicted_return >= _cfg.min_predicted_return;

	if (_position_qty > 0.0 && want_short)
	{
		return close_position(ts_ms, mid_price, "flip_to_short");
	}
	if (_position_qty < 0.0 && want_long)
	{
		return close_position(ts_ms, mid_price, "flip_to_long");
	}

	if (_position_qty == 0.0)
	{
		if (want_long)
		{
			return open_position(ts_ms, mid_price, true);
		}
		if (want_short)
		{
			return open_position(ts_ms, mid_price, false);
		}
	}

	return std::nullopt;
}

std::optional<PaperSimulatorEvent> PaperSimulator::close_all(std::int64_t ts_ms, double mid_price, const char* reason)
{
	if (_position_qty == 0.0)
	{
		return std::nullopt;
	}
	return close_position(ts_ms, mid_price, reason);
}

PaperSimulatorSnapshot PaperSimulator::snapshot() const
{
	PaperSimulatorSnapshot out{};
	out.cash_usd = _cash_usd;
	out.position_qty = _position_qty;
	out.entry_price = _entry_price;
	out.mark_price = _last_mark_price;
	out.equity_usd = equity_usd();
	out.realized_pnl_usd = _realized_pnl_usd;
	out.unrealized_pnl_usd = _position_qty * (_last_mark_price - _entry_price);
	out.fees_paid_usd = _fees_paid_usd;
	out.trade_count = _trade_count;
	out.win_count = _win_count;
	out.loss_count = _loss_count;
	return out;
}

std::optional<PaperSimulatorEvent> PaperSimulator::open_position(std::int64_t ts_ms, double mid_price, bool long_side)
{
	if (!(_cfg.trade_notional_usd > 0.0))
	{
		return std::nullopt;
	}

	const bool buy_side = long_side;
	const double fill_px = apply_slippage(mid_price, buy_side, _cfg.slippage_bps);
	if (!(fill_px > 0.0))
	{
		return std::nullopt;
	}
	const double qty = _cfg.trade_notional_usd / fill_px;
	if (!(qty > 0.0))
	{
		return std::nullopt;
	}

	const double signed_qty = long_side ? qty : -qty;
	const double gross_cash = signed_qty * fill_px;
	const double fee = std::abs(gross_cash) * (_cfg.fee_bps / kBpsDenominator);

	_cash_usd -= gross_cash;
	_cash_usd -= fee;
	_fees_paid_usd += fee;
	_position_qty = signed_qty;
	_entry_price = fill_px;
	_position_open_ts_ms = ts_ms;
	_trade_count += 1;

	PaperSimulatorEvent out{};
	out.action = long_side ? "OPEN_LONG" : "OPEN_SHORT";
	out.fill_price = fill_px;
	out.fill_qty = signed_qty;
	return out;
}

std::optional<PaperSimulatorEvent> PaperSimulator::close_position(std::int64_t ts_ms, double mid_price, const char* reason)
{
	if (_position_qty == 0.0)
	{
		return std::nullopt;
	}

	const bool close_buy = _position_qty < 0.0;
	const double fill_px = apply_slippage(mid_price, close_buy, _cfg.slippage_bps);
	const double gross_cash = _position_qty * fill_px;
	const double fee = std::abs(gross_cash) * (_cfg.fee_bps / kBpsDenominator);

	_cash_usd += gross_cash;
	_cash_usd -= fee;
	_fees_paid_usd += fee;

	const double realized = _position_qty * (fill_px - _entry_price);
	_realized_pnl_usd += realized;
	if (realized > 0.0)
	{
		_win_count += 1;
	}
	else if (realized < 0.0)
	{
		_loss_count += 1;
	}

	PaperSimulatorEvent out{};
	out.action = std::string("CLOSE(") + reason + ")";
	out.fill_price = fill_px;
	out.fill_qty = -_position_qty;
	out.realized_pnl_usd = realized;

	_position_qty = 0.0;
	_entry_price = 0.0;
	_position_open_ts_ms = ts_ms;
	return out;
}

double PaperSimulator::apply_slippage(double mid_price, bool buy_side, double slippage_bps)
{
	const double slip = std::max(0.0, slippage_bps) / kBpsDenominator;
	return buy_side ? mid_price * (1.0 + slip) : mid_price * (1.0 - slip);
}

double PaperSimulator::equity_usd() const
{
	return _cash_usd + _position_qty * _last_mark_price;
}
