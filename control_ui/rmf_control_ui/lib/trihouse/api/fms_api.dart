import 'fms_models.dart';

/// The only runtime backend boundary exposed to Control UI pages.
abstract interface class FmsApi {
  Future<List<InventoryLotDto>> listInventory();

  Future<List<MapProjectSummaryDto>> listMapProjects();

  Future<MapProjectOpenDto> openMapProject(String mapName);

  Future<StagedMapSourceDto> stageMapSource(
    String mapName,
    MapSourceUploadDto source,
  );

  Future<MapProjectDraftDto> saveMapDraft(
    MapProjectDraftDto draft, {
    required int expectedRevision,
  });

  Future<void> deleteMapDraft(String mapName);

  Future<MapValidationDto> validateMapDraft(String mapName);

  Future<PublishedMapDto> publishMapDraft(
    String mapName,
    PublishMapDto request,
  );

  Future<RuntimeProfileDto> getRuntimeProfile();

  Future<OutboundOrderDto> createOutboundOrder(
    OutboundOrderRequestDto request, {
    required String idempotencyKey,
  });

  /// 원장의 작업 목록. 대시보드와 작업 관리 화면이 이것으로 살아난다.
  Future<List<JobSummaryDto>> listJobs();

  /// 등록된 주행 로봇과 로봇팔의 최신 관측 상태.
  Future<List<DeviceDto>> listDevices();

  /// 아직 확인되지 않은 예약 이상.
  Future<List<ReservationAnomalyDto>> listAnomalies();

  Future<JobDetailDto> getJob(int jobId);

  Future<JobDetailDto> completeJob(
    int jobId,
    WorkerCompletionDto request, {
    required String idempotencyKey,
  });

  Stream<OperationsEventDto> operationsEvents();

  Future<void> decideEmergency(
    int incidentId,
    EmergencyDecisionDto request, {
    required String idempotencyKey,
  });
}
