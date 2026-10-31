! SPDX-License-Identifier: Apache-2.0
! Cache exact linear FE quadrature weights on a fixed thermal mesh. Native
! SaveScalars independently verifies the final row in every transient run.
SUBROUTINE FastAudit(Model,Solver,dt,Transient)
  USE DefUtils
  IMPLICIT NONE
  TYPE(Model_t) :: Model
  TYPE(Solver_t), TARGET :: Solver
  REAL(KIND=dp) :: dt
  LOGICAL :: Transient
  TYPE :: HeaterData
    INTEGER, ALLOCATABLE :: idx(:)
    REAL(KIND=dp), ALLOCATABLE :: weights(:)
    REAL(KIND=dp) :: volume
  END TYPE
  TYPE(HeaterData), ALLOCATABLE, SAVE :: heaters(:)
  REAL(KIND=dp), ALLOCATABLE, SAVE :: energyW(:),areaW(:)
  LOGICAL, ALLOCATABLE, SAVE :: boardMask(:)
  TYPE(Variable_t), POINTER :: TempVar
  TYPE(Element_t), POINTER :: Element
  TYPE(ValueList_t), POINTER :: Params,Mat,BC
  TYPE(Nodes_t) :: Nodes
  TYPE(GaussIntegrationPoints_t) :: IP
  REAL(KIND=dp), ALLOCATABLE :: basis(:),hw(:,:),values(:),temp(:)
  REAL(KIND=dp) :: det,s,cap,localMin,localMax
  INTEGER :: n,nn,nh,i,j,k,g,h,u,ii
  LOGICAL :: Found,stat,isboard
  CHARACTER(:), ALLOCATABLE :: filename
  LOGICAL, SAVE :: first=.TRUE.

  TempVar=>VariableGet(Solver%Mesh%Variables,'Temperature')
  IF(.NOT.ASSOCIATED(TempVar)) CALL Fatal('FastAudit','Temperature is absent')
  nn=Solver%Mesh%NumberOfNodes
  nh=GetInteger(Solver%Values,'Thermal Heater Count')
  IF(first) THEN
    ALLOCATE(heaters(nh),energyW(nn),areaW(nn),boardMask(nn),hw(nn,nh))
    energyW=0;areaW=0;boardMask=.FALSE.;hw=0
    n=Solver%Mesh%MaxElementNodes
    ALLOCATE(basis(n),Nodes%x(n),Nodes%y(n),Nodes%z(n))
    DO i=1,Solver%Mesh%NumberOfBulkElements
      Element=>Solver%Mesh%Elements(i);Model%CurrentElement=>Element
      Params=>GetBodyParams(Element)
      Mat=>GetMaterial(Element)
      cap=GetConstReal(Mat,'Density')*GetConstReal(Mat,'Heat Capacity')
      h=GetInteger(Params,'Thermal Heater Index',Found)
      IF(.NOT.Found) h=0
      isboard=GetLogical(Params,'audit_board',Found)
      n=Element%Type%NumberOfNodes
      CALL GetElementNodes(Nodes)
      IP=GaussPoints(Element)
      DO g=1,IP%n
        stat=ElementInfo(Element,Nodes,IP%u(g),IP%v(g),IP%w(g),det,basis)
        s=det*IP%s(g)
        DO j=1,n
          ii=Element%NodeIndexes(j)
          energyW(ii)=energyW(ii)+s*basis(j)*cap
          IF(isboard) boardMask(ii)=.TRUE.
          IF(h>0) hw(ii,h)=hw(ii,h)+s*basis(j)
        END DO
      END DO
    END DO
    DO i=1,Solver%Mesh%NumberOfBoundaryElements
      Element=>GetBoundaryElement(i);BC=>GetBC()
      IF(.NOT.ASSOCIATED(BC)) CYCLE
      IF(.NOT.GetLogical(BC,'audit_exposed',Found)) CYCLE
      n=Element%Type%NumberOfNodes
      CALL GetElementNodes(Nodes)
      IP=GaussPoints(Element)
      DO g=1,IP%n
        stat=ElementInfo(Element,Nodes,IP%u(g),IP%v(g),IP%w(g),det,basis)
        s=det*IP%s(g)
        DO j=1,n
          ii=Element%NodeIndexes(j);areaW(ii)=areaW(ii)+s*basis(j)
        END DO
      END DO
    END DO
    DO h=1,nh
      heaters(h)%idx=PACK([(i,i=1,nn)],hw(:,h)>0)
      heaters(h)%weights=PACK(hw(:,h),hw(:,h)>0)
      heaters(h)%volume=ParallelReduction(SUM(heaters(h)%weights))
    END DO
    DEALLOCATE(hw,basis,Nodes%x,Nodes%y,Nodes%z)
    CALL Info('FastAudit','Cached bulk energy, exposed area and heater quadrature weights')
  END IF
  ALLOCATE(temp(nn),values(8+3*nh))
  temp=0
  DO i=1,nn
    IF(TempVar%Perm(i)>0) temp(i)=TempVar%Values(TempVar%Perm(i))
  END DO
  values(1)=GetTime()
  localMin=MINVAL(temp,MASK=TempVar%Perm>0);localMax=MAXVAL(temp,MASK=TempVar%Perm>0)
  values(2)=ParallelReduction(localMin,1)
  values(3)=ParallelReduction(localMax,2)
  values(4)=ParallelReduction(SUM(temp*energyW))
  values(5)=ParallelReduction(SUM(temp*areaW))
  values(6)=ParallelReduction(SUM(areaW))
  DO h=1,nh
    k=6+3*(h-1)
    localMin=HUGE(1.0_dp);localMax=-HUGE(1.0_dp)
    IF(SIZE(heaters(h)%idx)>0) THEN
      localMin=MINVAL(temp(heaters(h)%idx));localMax=MAXVAL(temp(heaters(h)%idx))
    END IF
    values(k+1)=ParallelReduction(localMin,1)
    values(k+2)=ParallelReduction(localMax,2)
    values(k+3)=ParallelReduction(SUM(temp(heaters(h)%idx)*heaters(h)%weights))/heaters(h)%volume
  END DO
  values(SIZE(values)-1)=ParallelReduction(MINVAL(temp,MASK=boardMask),1)
  values(SIZE(values))=ParallelReduction(MAXVAL(temp,MASK=boardMask),2)
  IF(ParEnv%MyPe==0) THEN
    filename=GetString(Solver%Values,'Filename')
    IF(first) THEN
      OPEN(NEWUNIT=u,FILE=filename,STATUS='replace',ACTION='write')
    ELSE
      OPEN(NEWUNIT=u,FILE=filename,STATUS='old',POSITION='append',ACTION='write')
    END IF
    WRITE(u,'(*(ES24.15E3,1X))') values
    CLOSE(u)
  END IF
  first=.FALSE.
  DEALLOCATE(temp,values)
END SUBROUTINE FastAudit
