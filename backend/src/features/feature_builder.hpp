#pragma once

#include "common/types.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <deque>
#include <functional>
#include <limits>
#include <map>
#include <optional>
#include <ostream>
#include <string>
#include <vector>

namespace trading
{
using DoubleType = double;

struct FeatureRow
{
	std::string inst_id;
	std::string book_action;

	std::uint64_t book_ts{};
	std::uint64_t book_recv_ts{};
	std::uint64_t book_seq_id{};

	DoubleType best_bid_px{};
	DoubleType best_ask_px{};
	DoubleType best_bid_sz{};
	DoubleType best_ask_sz{};

	DoubleType mid_price{};
	DoubleType spread{};
	DoubleType rel_spread{};
	DoubleType microprice{};
	DoubleType imbalance_l1{};
	DoubleType imbalance_l5{};
	DoubleType bid_vol_l5{};
	DoubleType ask_vol_l5{};
	DoubleType weighted_bid_depth{};
	DoubleType weighted_ask_depth{};

	std::size_t trade_count{};
	std::size_t buy_count{};
	std::size_t sell_count{};

	DoubleType trade_volume{};
	DoubleType buy_volume{};
	DoubleType sell_volume{};
	DoubleType trade_imbalance{};

	DoubleType trade_vwap{};
	DoubleType trade_vwap_dev_from_mid{};

	DoubleType prev_mid_price{};
	DoubleType prev_spread{};
	DoubleType delta_mid_price{};
	DoubleType delta_spread{};
	DoubleType delta_imbalance_l5{};
};

inline std::ostream& operator<<(std::ostream& os, const FeatureRow& row)
{
	os
		<< "FeatureRow{" << "inst_id=" << row.inst_id << ", book_ts=" << row.book_ts << ", seq_id="
		<< row.book_seq_id << ", book_action=" << row.book_action
		<< ", best_bid_px=" << row.best_bid_px << ", best_ask_px=" << row.best_ask_px
		<< ", mid_price=" << row.mid_price << ", spread=" << row.spread << ", microprice=" << row.microprice
		<< ", imbalance_l1=" << row.imbalance_l1 << ", imbalance_l5=" << row.imbalance_l5
		<< ", trade_count=" << row.trade_count << ", buy_count=" << row.buy_count
		<< ", sell_count=" << row.sell_count << ", trade_volume=" << row.trade_volume
		<< ", buy_volume=" << row.buy_volume << ", sell_volume=" << row.sell_volume
		<< ", trade_imbalance=" << row.trade_imbalance << ", trade_vwap=" << row.trade_vwap
		<< ", trade_vwap_dev_from_mid=" << row.trade_vwap_dev_from_mid
		<< ", delta_mid_price=" << row.delta_mid_price << ", delta_spread=" << row.delta_spread
		<< ", delta_imbalance_l5=" << row.delta_imbalance_l5 << "}";
	return os;
}

class FeatureBuilder
{
public:
	struct Config
	{
		std::uint64_t trade_lookback_ms{100};
		bool use_exchange_ts_for_alignment{true};
	};

public:
	FeatureBuilder()
		: FeatureBuilder(Config{})
	{
	}

	explicit FeatureBuilder(Config cfg)
		: m_cfg(cfg)
	{
	}

	void on_trade(const Trade& t)
	{
		m_trades.push_back(t);
		const auto now_ts = choose_trade_time(t);
		evict_old_trades(now_ts);
	}

	std::optional<FeatureRow> on_books(const Books5& b)
	{
		return build_feature_row(b, b.action.empty() ? "snapshot" : b.action);
	}

	std::optional<FeatureRow> on_books(const Books& b)
	{
		if (b.bids.empty() && b.asks.empty())
		{
			return std::nullopt;
		}

		Books5 b5;
		b5.instrument_id = b.instrument_id;
		b5.exchange_ts_ms = b.exchange_ts_ms;
		b5.recv_ts_ms = b.recv_ts_ms;
		b5.sequence_id = b.sequence_id;

		auto& state = m_books_by_inst[b.instrument_id];
		b5.action = normalize_action(b.action, !state.bids.empty() || !state.asks.empty());
		apply_books_update(state, b);
		if (!materialize_top5(state, b5))
		{
			return std::nullopt;
		}

		return build_feature_row(b5, b5.action);
	}

private:
	struct BookState
	{
		std::map<DoubleType, DoubleType, std::greater<DoubleType>> bids;
		std::map<DoubleType, DoubleType> asks;
	};

	Config m_cfg;
	std::deque<Trade> m_trades{};
	std::optional<Books5> m_last_book{};
	std::map<std::string, BookState> m_books_by_inst{};

	std::optional<DoubleType> m_prev_mid_price{};
	std::optional<DoubleType> m_prev_spread{};
	std::optional<DoubleType> m_prev_imbalance_l5{};

private:
	static constexpr DoubleType k_eps = 1e-12;

private:
	static std::string normalize_action(const std::string& action, bool has_state)
	{
		if (action == "snapshot" || action == "update")
		{
			return action;
		}
		return has_state ? "update" : "snapshot";
	}

	static DoubleType to_scalar(const ::DoubleType& value)
	{
		return value.convert_to<double>();
	}

	static ::DoubleType from_scalar(DoubleType value)
	{
		return ::DoubleType(value);
	}

	std::uint64_t choose_trade_time(const Trade& t) const
	{
		return m_cfg.use_exchange_ts_for_alignment ? t.exchange_ts_ms : t.recv_ts_ms;
	}

	std::uint64_t choose_book_time(const Books5& b) const
	{
		return m_cfg.use_exchange_ts_for_alignment ? b.exchange_ts_ms : b.recv_ts_ms;
	}

	void evict_old_trades(std::uint64_t now_ts)
	{
		const std::uint64_t cutoff = (now_ts > m_cfg.trade_lookback_ms) ? (now_ts - m_cfg.trade_lookback_ms) : 0;

		while (!m_trades.empty())
		{
			const auto& t = m_trades.front();
			const auto trade_ts = choose_trade_time(t);
			if (trade_ts >= cutoff)
			{
				break;
			}
			m_trades.pop_front();
		}
	}

	static bool is_valid_book(const Books5& b)
	{
		if (to_scalar(b.bids[0].price) <= 0.0 || to_scalar(b.asks[0].price) <= 0.0)
		{
			return false;
		}
		if (to_scalar(b.bids[0].quantity) < 0.0 || to_scalar(b.asks[0].quantity) < 0.0)
		{
			return false;
		}
		if (to_scalar(b.bids[0].price) > to_scalar(b.asks[0].price))
		{
			return false;
		}
		return true;
	}

	static void apply_side_update(std::map<DoubleType, DoubleType, std::greater<DoubleType>>& side,
								  const std::vector<Book>& levels)
	{
		for (const auto& level : levels)
		{
			const auto px = to_scalar(level.price);
			const auto sz = to_scalar(level.quantity);
			if (!(px > 0.0))
			{
				continue;
			}
			if (sz <= 0.0)
			{
				side.erase(px);
			}
			else
			{
				side[px] = sz;
			}
		}
	}

	static void apply_side_update(std::map<DoubleType, DoubleType>& side, const std::vector<Book>& levels)
	{
		for (const auto& level : levels)
		{
			const auto px = to_scalar(level.price);
			const auto sz = to_scalar(level.quantity);
			if (!(px > 0.0))
			{
				continue;
			}
			if (sz <= 0.0)
			{
				side.erase(px);
			}
			else
			{
				side[px] = sz;
			}
		}
	}

	static void apply_books_update(BookState& state, const Books& b)
	{
		const auto action = normalize_action(b.action, !state.bids.empty() || !state.asks.empty());
		if (action == "snapshot")
		{
			state.bids.clear();
			state.asks.clear();
		}
		apply_side_update(state.bids, b.bids);
		apply_side_update(state.asks, b.asks);
	}

	static bool materialize_top5(const BookState& state, Books5& out)
	{
		if (state.bids.empty() || state.asks.empty())
		{
			return false;
		}

		std::size_t idx = 0;
		for (const auto& [px, sz] : state.bids)
		{
			if (idx >= out.bids.size())
			{
				break;
			}
			out.bids[idx].price = from_scalar(px);
			out.bids[idx].quantity = from_scalar(sz);
			++idx;
		}

		idx = 0;
		for (const auto& [px, sz] : state.asks)
		{
			if (idx >= out.asks.size())
			{
				break;
			}
			out.asks[idx].price = from_scalar(px);
			out.asks[idx].quantity = from_scalar(sz);
			++idx;
		}

		return true;
	}

	std::optional<FeatureRow> build_feature_row(const Books5& b, const std::string& action)
	{
		if (!is_valid_book(b))
		{
			return std::nullopt;
		}

		const std::uint64_t now_ts = choose_book_time(b);
		evict_old_trades(now_ts);

		FeatureRow row{};
		row.inst_id = b.instrument_id;
		row.book_action = normalize_action(action, m_last_book.has_value());
		row.book_ts = b.exchange_ts_ms;
		row.book_recv_ts = b.recv_ts_ms;
		row.book_seq_id = b.sequence_id;

		row.best_bid_px = to_scalar(b.bids[0].price);
		row.best_ask_px = to_scalar(b.asks[0].price);
		row.best_bid_sz = to_scalar(b.bids[0].quantity);
		row.best_ask_sz = to_scalar(b.asks[0].quantity);

		row.mid_price = compute_mid_price(b);
		row.spread = compute_spread(b);
		row.rel_spread = safe_div(row.spread, row.mid_price);
		row.microprice = compute_microprice(b);
		row.imbalance_l1 = compute_level_imbalance(b, 1);
		row.imbalance_l5 = compute_level_imbalance(b, 5);
		row.bid_vol_l5 = sum_bid_volume(b, 5);
		row.ask_vol_l5 = sum_ask_volume(b, 5);
		row.weighted_bid_depth = compute_weighted_bid_depth(b, 5);
		row.weighted_ask_depth = compute_weighted_ask_depth(b, 5);

		fill_trade_features(now_ts, row);

		row.prev_mid_price = m_prev_mid_price.value_or(row.mid_price);
		row.prev_spread = m_prev_spread.value_or(row.spread);
		row.delta_mid_price = row.mid_price - row.prev_mid_price;
		row.delta_spread = row.spread - row.prev_spread;
		row.delta_imbalance_l5 = row.imbalance_l5 - m_prev_imbalance_l5.value_or(row.imbalance_l5);

		m_prev_mid_price = row.mid_price;
		m_prev_spread = row.spread;
		m_prev_imbalance_l5 = row.imbalance_l5;
		m_last_book = b;

		return row;
	}

	static DoubleType safe_div(DoubleType num, DoubleType den)
	{
		if (std::abs(den) < k_eps)
		{
			return 0.0;
		}
		return num / den;
	}

	static DoubleType compute_mid_price(const Books5& b)
	{
		return (to_scalar(b.bids[0].price) + to_scalar(b.asks[0].price)) / 2.0;
	}

	static DoubleType compute_spread(const Books5& b)
	{
		return to_scalar(b.asks[0].price) - to_scalar(b.bids[0].price);
	}

	static DoubleType compute_microprice(const Books5& b)
	{
		const auto bid_px = to_scalar(b.bids[0].price);
		const auto ask_px = to_scalar(b.asks[0].price);
		const auto bid_sz = to_scalar(b.bids[0].quantity);
		const auto ask_sz = to_scalar(b.asks[0].quantity);
		const auto den = bid_sz + ask_sz;
		if (std::abs(den) < k_eps)
		{
			return (bid_px + ask_px) / 2.0;
		}
		return (ask_px * bid_sz + bid_px * ask_sz) / den;
	}

	static DoubleType sum_bid_volume(const Books5& b, std::size_t levels)
	{
		const std::size_t n = std::min<std::size_t>(levels, b.bids.size());
		DoubleType total = 0.0;
		for (std::size_t i = 0; i < n; ++i)
		{
			total += to_scalar(b.bids[i].quantity);
		}
		return total;
	}

	static DoubleType sum_ask_volume(const Books5& b, std::size_t levels)
	{
		const std::size_t n = std::min<std::size_t>(levels, b.asks.size());
		DoubleType total = 0.0;
		for (std::size_t i = 0; i < n; ++i)
		{
			total += to_scalar(b.asks[i].quantity);
		}
		return total;
	}

	static DoubleType compute_level_imbalance(const Books5& b, std::size_t levels)
	{
		const auto bid_vol = sum_bid_volume(b, levels);
		const auto ask_vol = sum_ask_volume(b, levels);
		return safe_div(bid_vol - ask_vol, bid_vol + ask_vol);
	}

	static DoubleType compute_weighted_bid_depth(const Books5& b, std::size_t levels)
	{
		const std::size_t n = std::min<std::size_t>(levels, b.bids.size());
		DoubleType total = 0.0;
		for (std::size_t i = 0; i < n; ++i)
		{
			const DoubleType weight = 1.0 / static_cast<DoubleType>(i + 1);
			total += to_scalar(b.bids[i].quantity) * weight;
		}
		return total;
	}

	static DoubleType compute_weighted_ask_depth(const Books5& b, std::size_t levels)
	{
		const std::size_t n = std::min<std::size_t>(levels, b.asks.size());
		DoubleType total = 0.0;
		for (std::size_t i = 0; i < n; ++i)
		{
			const DoubleType weight = 1.0 / static_cast<DoubleType>(i + 1);
			total += to_scalar(b.asks[i].quantity) * weight;
		}
		return total;
	}

	void fill_trade_features(std::uint64_t now_ts, FeatureRow& row) const
	{
		DoubleType notional = 0.0;

		for (const auto& t : m_trades)
		{
			if (t.instrument_id != row.inst_id)
			{
				continue;
			}

			const auto t_ts = choose_trade_time(t);
			if (t_ts > now_ts)
			{
				continue;
			}

			row.trade_count += 1;
			const auto sz = to_scalar(t.size);
			const auto px = to_scalar(t.price);
			row.trade_volume += sz;
			notional += px * sz;

			if (t.side == "buy")
			{
				row.buy_count += 1;
				row.buy_volume += sz;
			}
			else if (t.side == "sell")
			{
				row.sell_count += 1;
				row.sell_volume += sz;
			}
		}

		row.trade_imbalance = safe_div(row.buy_volume - row.sell_volume, row.buy_volume + row.sell_volume);
		row.trade_vwap = (row.trade_volume > 0.0) ? (notional / row.trade_volume) : row.mid_price;
		row.trade_vwap_dev_from_mid = safe_div(row.trade_vwap - row.mid_price, row.mid_price);
	}
};

}  // namespace trading
