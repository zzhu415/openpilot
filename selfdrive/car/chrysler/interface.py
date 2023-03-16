#!/usr/bin/env python3
from cereal import car
from common.params import Params
from panda import Panda
from selfdrive.car import STD_CARGO_KG, get_safety_config
from selfdrive.car.chrysler.values import CAR, DBC, RAM_HD, RAM_DT, RAM_CARS, ChryslerFlags
from selfdrive.car.interfaces import CarInterfaceBase

ButtonType = car.CarState.ButtonEvent.Type
EventName = car.CarEvent.EventName
GearShifter = car.CarState.GearShifter


class CarInterface(CarInterfaceBase):
  @staticmethod
  def _get_params(ret, candidate, fingerprint, car_fw, experimental_long):
    ret.carName = "chrysler"
    #ret.dashcamOnly = candidate in RAM_HD

    ret.radarOffCan = DBC[candidate]['radar'] is None
    ret.steerActuatorDelay = 0.1
    ret.steerLimitTimer = 0.4
    stiffnessFactor = 1.0

    # safety config
    ret.safetyConfigs = [get_safety_config(car.CarParams.SafetyModel.chrysler)]
    if candidate in RAM_HD:
      ret.safetyConfigs[0].safetyParam |= Panda.FLAG_CHRYSLER_RAM_HD
    elif candidate in RAM_DT:
      ret.safetyConfigs[0].safetyParam |= Panda.FLAG_CHRYSLER_RAM_DT

    ret.minSteerSpeed = 3.8  # m/s
    if candidate not in RAM_CARS:
      # Newer FW versions standard on the following platforms, or flashed by a dealer onto older platforms have a higher minimum steering speed.
      new_eps_platform = candidate in (CAR.PACIFICA_2019_HYBRID, CAR.PACIFICA_2020, CAR.JEEP_CHEROKEE_2019)
      new_eps_firmware = any(fw.ecu == 'eps' and fw.fwVersion[:4] >= b"6841" for fw in car_fw)
      if new_eps_platform or new_eps_firmware:
        ret.flags |= ChryslerFlags.HIGHER_MIN_STEERING_SPEED.value

    # Chrysler
    if candidate in (CAR.PACIFICA_2017_HYBRID, CAR.PACIFICA_2018, CAR.PACIFICA_2018_HYBRID, CAR.PACIFICA_2019_HYBRID, CAR.PACIFICA_2020):
      ret.mass = 2242. + STD_CARGO_KG
      ret.wheelbase = 3.089
      ret.steerRatio = 16.2  # Pacifica Hybrid 2017
      ret.lateralTuning.pid.kpBP, ret.lateralTuning.pid.kiBP = [[9., 20.], [9., 20.]]
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.15, 0.30], [0.03, 0.05]]
      ret.lateralTuning.pid.kf = 0.00006

    # Jeep
    elif candidate in (CAR.JEEP_CHEROKEE, CAR.JEEP_CHEROKEE_2019):
      ret.mass = 1778 + STD_CARGO_KG
      ret.wheelbase = 2.71
      ret.steerRatio = 16.7
      ret.steerActuatorDelay = 0.2
      ret.lateralTuning.pid.kpBP, ret.lateralTuning.pid.kiBP = [[9., 20.], [9., 20.]]
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.15, 0.30], [0.03, 0.05]]
      ret.lateralTuning.pid.kf = 0.00006

    # Ram
    elif candidate == CAR.RAM_1500:
      ret.steerActuatorDelay = 0.2
      ret.wheelbase = 3.88
      ret.steerRatio = 16.3
      ret.mass = 2493. + STD_CARGO_KG
      CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)
      ret.minSteerSpeed = 0.5
      ret.minEnableSpeed = 14.6
      for fw in car_fw:
        if fw.ecu == 'eps' and fw.fwVersion.startswith((b"68312176", b"68273275")):
          ret.minSteerSpeed = 0.

    elif candidate == CAR.RAM_HD:
      stiffnessFactor = 0.35
      ret.steerActuatorDelay = 0.25
      ret.wheelbase = 3.785
      ret.steerRatio = 15.61
      ret.mass = 3405. + STD_CARGO_KG
      ret.minSteerSpeed = 16
      CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning, 1.0, False)

    else:
      raise ValueError(f"Unsupported car: {candidate}")

    if Params().get_bool("EnforceTorqueLateral"):
      CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)

    if ret.flags & ChryslerFlags.HIGHER_MIN_STEERING_SPEED:
      # TODO: allow these cars to steer down to 13 m/s if already engaged.
      ret.minSteerSpeed = 17.5  # m/s 17 on the way up, 13 on the way down once engaged.

    ret.centerToFront = ret.wheelbase * 0.44
    ret.enableBsm = 720 in fingerprint[0]

    return ret

  def _update(self, c):
    ret = self.CS.update(self.cp, self.cp_cam)

    ret.madsEnabled = self.CS.madsEnabled
    ret.accEnabled = self.CS.accEnabled
    ret.leftBlinkerOn = self.CS.leftBlinkerOn
    ret.rightBlinkerOn = self.CS.rightBlinkerOn
    ret.belowLaneChangeSpeed = self.CS.belowLaneChangeSpeed

    buttonEvents = []

    # MADS BUTTON
    if self.CS.out.madsEnabled != self.CS.madsEnabled:
      be = car.CarState.ButtonEvent.new_message()
      be.pressed = True
      be.type = ButtonType.altButton1
      buttonEvents.append(be)

    ret.buttonEvents = buttonEvents

    # events
    events = self.create_common_events(ret, extra_gears=[car.CarState.GearShifter.low], pcm_enable=False)

    if self.CP.carFingerprint in RAM_DT:
      if self.CS.out.vEgo >= self.CP.minEnableSpeed:
        self.low_speed_alert = False
      if (self.CP.minEnableSpeed >= 14.5)  and (self.CS.out.gearShifter != GearShifter.drive) :
        self.low_speed_alert = True

    else:  # Low speed steer alert hysteresis logic
      if self.CP.minSteerSpeed > 0. and ret.vEgo < (self.CP.minSteerSpeed + 0.5):
        self.low_speed_alert = True
      elif ret.vEgo > (self.CP.minSteerSpeed + 1.):
        self.low_speed_alert = False
    if self.low_speed_alert and self.CS.madsEnabled:
      events.add(car.CarEvent.EventName.belowSteerSpeed)

    self.CS.disengageByBrake = self.CS.disengageByBrake or ret.disengageByBrake

    enable_pressed = False
    enable_from_brake = False

    if self.CS.disengageByBrake and not ret.brakePressed and not ret.brakeHoldActive and not ret.parkingBrake and \
      self.CS.madsEnabled:
      enable_pressed = True
      enable_from_brake = True

    if not ret.brakePressed and not ret.brakeHoldActive and not ret.parkingBrake:
      self.CS.disengageByBrake = False
      ret.disengageByBrake = False

    if self.CP.pcmCruise:
      # do disable on button down
      if not ret.cruiseState.enabled and self.CS.out.cruiseState.enabled:
        if not self.CS.madsEnabled:
          events.add(EventName.buttonCancel)
        elif not self.cruise_cancelled_btn:
          self.cruise_cancelled_btn = True
          events.add(EventName.manualLongitudinalRequired)
      # do enable on both accel and decel buttons
      if ret.cruiseState.enabled and not self.CS.out.cruiseState.enabled:
        enable_pressed = True

    for b in ret.buttonEvents:
      # do disable on MADS button if ACC is disabled
      if b.type == ButtonType.altButton1 and b.pressed:
        if not self.CS.madsEnabled: # disabled MADS
          if not ret.cruiseState.enabled:
            events.add(EventName.buttonCancel)
          else:
            events.add(EventName.manualSteeringRequired)
        else: # enabled MADS
          if not ret.cruiseState.enabled:
            enable_pressed = True
    if (ret.cruiseState.enabled or self.CS.madsEnabled) and enable_pressed:
      if enable_from_brake:
        events.add(EventName.silentButtonEnable)
      else:
        events.add(EventName.buttonEnable)

    if ret.cruiseState.enabled:
      self.cruise_cancelled_btn = False

    ret.events = events.to_msg()

    return ret

  def apply(self, c):
    return self.CC.update(c, self.CS)
