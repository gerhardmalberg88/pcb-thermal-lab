! SPDX-License-Identifier: Apache-2.0
! Cache invariant bulk matrices using Elmer HeatSolver's documented interface.
! Update its cached source vector explicitly: Constant Bulk System alone would
! incorrectly freeze a time-dependent Heat Source. Boundary and time assembly
! remain Elmer operations. Valid only for constant materials, dt and convection.
SUBROUTINE ScheduledHeat(Model,Solver,dt,Transient)
  USE DefUtils
  IMPLICIT NONE
  TYPE(Model_t) :: Model
  TYPE(Solver_t), TARGET :: Solver
  REAL(KIND=dp) :: dt
  LOGICAL :: Transient
  TYPE(Element_t), POINTER :: Element
  TYPE(ValueList_t), POINTER :: BF
  TYPE(Nodes_t) :: Nodes
  TYPE(GaussIntegrationPoints_t) :: IP
  REAL(KIND=dp), ALLOCATABLE, SAVE :: Odd(:),Even(:)
  REAL(KIND=dp), ALLOCATABLE :: Basis(:)
  REAL(KIND=dp) :: qo,qe,det,s,on,phase,t
  INTEGER :: i,j,g,n,p
  LOGICAL :: Found,stat
  EXTERNAL :: HeatSolver

  IF(ALLOCATED(Odd)) THEN
    IF(SIZE(Odd)/=SIZE(Solver%Matrix%RHS)) CALL Fatal('ScheduledHeat','Mesh changed during cached solve')
    t=GetTime()
    on=GetConstReal(Solver%Values,'Thermal On Seconds')
    phase=GetConstReal(Solver%Values,'Thermal Phase Seconds')
    IF(t>on) THEN
      Solver%Matrix%BulkRHS=0.0_dp
    ELSE IF(MOD(INT(FLOOR((t-1.0e-8_dp)/phase)),2)==0) THEN
      Solver%Matrix%BulkRHS=Odd
    ELSE
      Solver%Matrix%BulkRHS=Even
    END IF
  END IF

  CALL HeatSolver(Model,Solver,dt,Transient)

  IF(.NOT.ALLOCATED(Odd)) THEN
    IF(.NOT.ASSOCIATED(Solver%Matrix%BulkRHS)) CALL Fatal('ScheduledHeat','Constant Bulk System is required')
    ALLOCATE(Odd(SIZE(Solver%Matrix%RHS)),Even(SIZE(Solver%Matrix%RHS)))
    Odd=0.0_dp;Even=0.0_dp
    n=Solver%Mesh%MaxElementNodes
    ALLOCATE(Basis(n),Nodes%x(n),Nodes%y(n),Nodes%z(n))
    DO i=1,Solver%NumberOfActiveElements
      Element=>GetActiveElement(i)
      BF=>GetBodyForce()
      IF(.NOT.ASSOCIATED(BF)) CYCLE
      qo=GetConstReal(BF,'Thermal Odd Source Wm3',Found)
      IF(.NOT.Found) CYCLE
      qe=GetConstReal(BF,'Thermal Even Source Wm3')
      CALL GetElementNodes(Nodes)
      n=GetElementNOFNodes()
      IP=GaussPoints(Element)
      DO g=1,IP%n
        stat=ElementInfo(Element,Nodes,IP%u(g),IP%v(g),IP%w(g),det,Basis)
        s=det*IP%s(g)
        DO j=1,n
          p=Solver%Variable%Perm(Element%NodeIndexes(j))
          IF(p>0) THEN
            Odd(p)=Odd(p)+qo*s*Basis(j)
            Even(p)=Even(p)+qe*s*Basis(j)
          END IF
        END DO
      END DO
    END DO
    DEALLOCATE(Basis,Nodes%x,Nodes%y,Nodes%z)
    CALL Info('ScheduledHeat','Cached invariant bulk matrices and independently integrated odd/even source vectors')
  END IF
END SUBROUTINE ScheduledHeat
