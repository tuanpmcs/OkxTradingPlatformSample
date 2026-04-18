#pragma once

#include "feature_builder.h"
#include "feature_csv_writer.h"
#include "grpc_stream.h"
#include "market_stream.h"

#include <map>
#include <memory>
#include <optional>
#include <string>

class RuntimeStreamHandler final : public MarketEventListener
{
public:
	RuntimeStreamHandler(std::optional<double>&					 last_price,
					 std::map<std::string, std::string>& previous_fields,
					 std::unique_ptr<CsvTickWriter>&	 csv_writer,
					 std::unique_ptr<GrpcServerRuntime>& grpc_server,
					 GrpcTickHub&						 grpc_hub,
					 const std::string&				 feature_csv_path = "");

	void on_trades(const Trades& trades, const std::string& raw_json) override;
	void on_books5(const Books5& books5, const std::string& raw_json) override;
	void on_books(const Books& books, const std::string& raw_json) override;

private:
	void emit(StreamRecord&& record);

private:
	std::optional<double>&					  _last_price;
	std::map<std::string, std::string>& _previous_fields;
	std::unique_ptr<CsvTickWriter>&	  _csv_writer;
	std::unique_ptr<GrpcServerRuntime>& _grpc_server;
	GrpcTickHub&							  _grpc_hub;
	FeatureAccumulator					  _features;
	trading::feature_builder			  _feature_builder;
	std::unique_ptr<trading::feature_csv_writer> _feature_csv_writer;
};
