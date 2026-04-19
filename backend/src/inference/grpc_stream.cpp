#include "inference/grpc_stream.hpp"

#include <algorithm>
#include <stdexcept>
#include <string>

bool GrpcTickHub::Subscriber::wait_pop(std::shared_ptr<const StreamRecord>& event, std::chrono::milliseconds timeout)
{
	std::unique_lock<std::mutex> lock(mutex);
	cv.wait_for(lock, timeout, [this]() {
		return closed || !queue.empty();
	});

	if (queue.empty())
	{
		return false;
	}

	event = queue.front();
	queue.pop_front();
	return true;
}

std::shared_ptr<GrpcTickHub::Subscriber> GrpcTickHub::add_subscriber()
{
	auto						subscriber = std::make_shared<Subscriber>();
	std::lock_guard<std::mutex> lock(_mutex);
	_subscribers.push_back(subscriber);
	return subscriber;
}

void GrpcTickHub::remove_subscriber(const std::shared_ptr<Subscriber>& target)
{
	std::lock_guard<std::mutex> lock(_mutex);
	_subscribers.erase(
			std::remove(_subscribers.begin(), _subscribers.end(), target),
			_subscribers.end());
}

void GrpcTickHub::broadcast(StreamRecord&& event)
{
	auto shared_event = std::make_shared<const StreamRecord>(std::move(event));

	std::vector<std::shared_ptr<Subscriber>> snapshot;
	{
		std::lock_guard<std::mutex> lock(_mutex);
		snapshot = _subscribers;
	}

	for (auto& subscriber : snapshot)
	{
		{
			std::lock_guard<std::mutex> lock(subscriber->mutex);
			subscriber->queue.push_back(shared_event);
			if (subscriber->queue.size() > 1024)
			{
				subscriber->queue.pop_front();
			}
		}
		subscriber->cv.notify_one();
	}
}

void GrpcTickHub::shutdown()
{
	std::vector<std::shared_ptr<Subscriber>> snapshot;
	{
		std::lock_guard<std::mutex> lock(_mutex);
		snapshot = _subscribers;
		_subscribers.clear();
	}

	for (auto& subscriber : snapshot)
	{
		{
			std::lock_guard<std::mutex> lock(subscriber->mutex);
			subscriber->closed = true;
		}
		subscriber->cv.notify_all();
	}
}

MarketDataServiceImpl::MarketDataServiceImpl(
		GrpcTickHub& hub,
		RuntimeSubscriptionRegistry* runtime_subscriptions)
	  : _hub(hub), _runtime_subscriptions(runtime_subscriptions)
{
}

grpc::Status MarketDataServiceImpl::Subscribe(grpc::ServerContext* context,
											  const marketstream::SubscribeRequest* request,
											  grpc::ServerWriter<marketstream::Tick>* writer)
{
	auto			  subscriber = _hub.add_subscriber();
	const std::string requested_channel = request ? request->channel() : "";
	const std::string requested_symbol = request ? request->symbol() : "";
	if (_runtime_subscriptions && !requested_channel.empty() && !requested_symbol.empty())
	{
		_runtime_subscriptions->request(requested_symbol, requested_channel);
	}

	while (!context->IsCancelled())
	{
		std::shared_ptr<const StreamRecord> event;
		if (!subscriber->wait_pop(event, std::chrono::milliseconds(250))) continue;

		if (!requested_channel.empty())
		{
			const auto it = event->fields.find("channel");
			if (it == event->fields.end() || it->second != requested_channel) continue;
		}

		if (!requested_symbol.empty())
		{
			const auto it = event->fields.find("instId");
			if (it == event->fields.end() || it->second != requested_symbol) continue;
		}

		marketstream::Tick tick;
		tick.set_ts(event->ts_ms);
		tick.set_price(event->price);
		tick.set_change(event->change);
		tick.set_source(event->source);
		for (const auto& [k, v] : event->fields)
		{
			(*tick.mutable_fields())[k] = v;
		}
		for (const auto& field_name : event->changed_fields)
		{
			tick.add_changed_fields(field_name);
		}

		if (!writer->Write(tick)) break;
	}

	_hub.remove_subscriber(subscriber);
	return grpc::Status::OK;
}

GrpcServerRuntime::GrpcServerRuntime(MarketDataServiceImpl& service,
									 marketstream::PredictionService::Service* prediction_service,
									 unsigned short port)
	  : _service(service), _prediction_service(prediction_service), _port(port)
{
}

GrpcServerRuntime::~GrpcServerRuntime()
{
	stop();
}

void GrpcServerRuntime::start()
{
	grpc::ServerBuilder builder;
	const std::string	address = "0.0.0.0:" + std::to_string(_port);
	builder.AddListeningPort(address, grpc::InsecureServerCredentials());
	builder.RegisterService(&_service);
	if (_prediction_service)
	{
		builder.RegisterService(_prediction_service);
	}
	_server = builder.BuildAndStart();
	if (!_server)
	{
		throw std::runtime_error("Failed to start gRPC server on " + address);
	}

	_thread = std::thread([this]() {
		_server->Wait();
	});
}

void GrpcServerRuntime::stop()
{
	if (_stopped) return;
	_stopped = true;

	if (_server) _server->Shutdown();
	if (_thread.joinable()) _thread.join();
}

PredictionServiceProxyImpl::PredictionServiceProxyImpl(PredictionClient* prediction_client)
	: _prediction_client(prediction_client)
{
}

grpc::Status PredictionServiceProxyImpl::Predict(grpc::ServerContext*,
												 const marketstream::PredictRequest* request,
												 marketstream::PredictResponse* response)
{
	if (!_prediction_client || !request || !response)
	{
		return grpc::Status(grpc::StatusCode::UNAVAILABLE, "prediction client unavailable");
	}

	std::deque<marketstream::PricePoint> points;
	points.insert(points.end(), request->points().begin(), request->points().end());
	if (points.empty())
	{
		return grpc::Status(grpc::StatusCode::INVALID_ARGUMENT, "points must not be empty");
	}

	const std::string model_type = request->model_type();
	const std::string* model_override = model_type.empty() ? nullptr : &model_type;
	const auto result = _prediction_client->predict(request->symbol(),
													request->channel(),
													points,
													model_override);
	if (!result)
	{
		return grpc::Status(grpc::StatusCode::UNAVAILABLE, "prediction unavailable");
	}

	response->set_model_name(result->model_name);
	response->set_signal(result->signal);
	response->set_last_price(result->last_price);
	response->set_predicted_price(result->predicted_price);
	response->set_predicted_return(result->predicted_return);
	response->set_detail(result->detail);
	return grpc::Status::OK;
}
